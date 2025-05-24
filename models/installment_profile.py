from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64

class InstallmentProfile(models.Model):
    _name = 'sale.installment.profile'
    _description = 'Hồ sơ trả góp/trả chậm'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Tên hồ sơ", required=True, copy=False, readonly=True, default='Mới')
    email_body = fields.Html(string="Nội dung Email", default="""
        <p style="margin: 0px; padding: 0px; font-size: 13px; margin-top: 16px;">
            Chúng tôi xin gửi hợp đồng trả góp đã được phê duyệt của quý khách.
        </p>
        <p style="margin: 0px; padding: 0px; font-size: 13px; margin-top: 16px;">
            Vui lòng xem file đính kèm.
        </p>
    """)
    seller_id = fields.Many2one('res.partner', string="Bên bán", 
        default=lambda self: self.env['res.partner'].search([('name', '=', 'NUTIFOOD')], limit=1),
        required=True)
    company_id = fields.Many2one(
        'res.company', 
        string='Company', 
        required=True, 
        default=lambda self: self.env.company,
        store=True
    )
    partner_id = fields.Many2one('res.partner', string="Khách hàng", required=True)
    sale_order_id = fields.Many2one('sale.order', string="Đơn hàng", required=True)
    mst = fields.Char(string="MST")
    address = fields.Text(string="Địa chỉ")
    attachment_ids = fields.Many2many('ir.attachment', string="Tài liệu tín dụng")
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('sent', 'Gửi Tài chính'),
        ('approved', 'Phê duyệt'),
        ('rejected', 'Từ chối'),
        ('cancelled', 'Đã hủy')
    ], string="Trạng thái", default='draft', tracking=True)

    # Copy fields from sale order for contract
    amount_total = fields.Monetary(related='sale_order_id.amount_total', string="Tổng tiền", readonly=True)
    currency_id = fields.Many2one('res.currency', string="Tiền tệ", default=lambda self: self.env.company.currency_id)
    amount_paid = fields.Monetary(related='sale_order_id.amount_paid', string="Số tiền đã trả", readonly=True)
    installment_months = fields.Integer(string="Số tháng trả góp")
    installment_day = fields.Integer(string="Ngày trả góp hàng tháng")
    late_fee_rate = fields.Float(string="Lãi suất phạt (%/tháng)")
    date_order = fields.Datetime(string="Ngày đặt hàng", default=fields.Datetime.now)

    _sql_constraints = [
        ('sale_order_id_uniq', 'UNIQUE(sale_order_id)', 'Mỗi đơn hàng chỉ có thể có một hồ sơ trả góp!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        profiles = super().create(vals_list)
        for profile in profiles:
            if profile.name == 'Mới' and not self.env.context.get('no_sequence_name'):
                profile.name = self.env['ir.sequence'].next_by_code('sale.installment.profile') or _('Mới')
            if profile.sale_order_id:
                profile.sale_order_id.write({'installment_profile_id': profile.id})
        return profiles

    def write(self, vals):
        # Store old sale_order_ids to clear their links if they change
        old_so_map = {profile.id: profile.sale_order_id for profile in self if 'sale_order_id' in vals}

        res = super().write(vals)

        if 'sale_order_id' in vals:
            for profile in self:
                new_so = profile.sale_order_id
                old_so = old_so_map.get(profile.id)

                # Clear link from old SO if it changed and is not the new SO
                if old_so and old_so != new_so:
                    if old_so.installment_profile_id == profile: # Only clear if it was linked to THIS profile
                        old_so.write({'installment_profile_id': False})
                
                # Set link on new SO
                if new_so:
                    if new_so.installment_profile_id and new_so.installment_profile_id != profile:
                        # This case should ideally be handled by the UNIQUE constraint
                        # or a warning, as another profile is already linked.
                        # For now, we overwrite, assuming the UNIQUE constraint on profile.sale_order_id
                        # is the primary guard.
                        pass
                    new_so.write({'installment_profile_id': profile.id})
        return res
    
    def unlink(self):
        # Clear the link on the sale order before deleting the profile
        for profile in self:
            if profile.sale_order_id and profile.sale_order_id.installment_profile_id == profile:
                profile.sale_order_id.write({'installment_profile_id': False})
        return super().unlink()

    def action_send_to_finance(self):
        self.write({'state': 'sent'})
        self.message_post(body=_('Hồ sơ đã được gửi đến bộ phận Tài chính'))

    def action_approve(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_('Cần có đơn hàng để phê duyệt hồ sơ trả góp!'))
            
        self.write({'state': 'approved'})
        self.message_post(body=_('Hồ sơ đã được phê duyệt'))
        
        # Automatically show contract after approval
        return self.env.ref('sale_installment.report_installment_contract_action').report_action(self)

    def action_reject(self):
        self.write({'state': 'rejected'})
        self.message_post(body=_('Hồ sơ đã bị từ chối'))

    def action_preview_contract(self):
        """Allows previewing the contract PDF."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_('Không thể xem trước hợp đồng khi chưa có đơn hàng liên kết.'))
        return self.env.ref('sale_installment.report_installment_contract_action').report_action(self)

    def action_send_contract_email(self):
        self.ensure_one()
        if not self.partner_id.email:
            raise UserError(_('Khách hàng chưa có địa chỉ email!'))

        # Get email template
        template = self.env.ref('sale_installment.email_template_installment_contract_editable')
        
        # Open email composer with the template
        compose_form = self.env.ref('mail.email_compose_message_wizard_form')
        ctx = dict(
            default_model=self._name,
            default_res_ids=[self.id],
            default_use_template=bool(template),
            default_template_id=template.id,
            default_composition_mode='comment',
            mark_so_as_sent=True,
            custom_layout='mail.mail_notification_light',
            force_email=True
        )
        
        return {
            'name': _('Gửi Hợp đồng qua Email'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'target': 'new',
            'context': ctx,
        }