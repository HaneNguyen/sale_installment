from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    installment_profile_id = fields.Many2one('sale.installment.profile', string="Hồ sơ trả góp", copy=False,)
    amount_paid = fields.Monetary(string="Số tiền đã trả", currency_field='currency_id', compute='_compute_amount_paid', store=True, help="Tổng số tiền đã thanh toán cho các hóa đơn của đơn hàng này.")
    installment_months = fields.Integer(
        related='installment_profile_id.installment_months', string="Số tháng trả góp",readonly=False, store=True)
    installment_day = fields.Integer(related='installment_profile_id.installment_day', string="Ngày trả góp hàng tháng", readonly=False, store=True)
    late_fee_rate = fields.Float(related='installment_profile_id.late_fee_rate', string="Lãi suất phạt (%/tháng)", readonly=False, store=True)

    @api.depends(
        'invoice_ids.state',
        'invoice_ids.move_type',            
        'invoice_ids.amount_total_signed',    
        'invoice_ids.amount_residual_signed', 
        'invoice_ids.payment_state',          
        'invoice_ids.currency_id',          
        'currency_id'                       
    )
    def _compute_amount_paid(self):
        _logger.info(f"--- TRIGGER COMPUTE: _compute_amount_paid for SOs: {self.mapped('name')} ---")
        for order in self:
            _logger.info(f"SO {order.name} (ID: {order.id}): Calculating amount_paid.")
            paid_amount_in_order_currency = 0.0

            if not order.invoice_ids:
                _logger.info(f"SO {order.name}: No invoices found. Amount paid set to 0.")
                order.amount_paid = 0.0
                continue

            _logger.info(f"SO {order.name}: Found {len(order.invoice_ids)} invoices: {order.invoice_ids.mapped('name')}")

            for inv in order.invoice_ids:
                _logger.info(
                    f"  SO {order.name} - Checking Invoice {inv.name} (ID: {inv.id}): "
                    f"State='{inv.state}', Type='{inv.move_type}', PaymentState='{inv.payment_state}', "
                    f"TotalSigned={inv.amount_total_signed}, ResidualSigned={inv.amount_residual_signed}, "
                    f"Currency={inv.currency_id.name}"
                )

                # Chỉ xử lý hóa đơn đã xác nhận và là hóa đơn khách hàng hoặc phiếu hoàn tiền
                if inv.state == 'posted' and inv.move_type in ('out_invoice', 'out_refund'):
                    # Tính số tiền đã được thanh toán/áp dụng trên hóa đơn này
                    paid_on_this_invoice = inv.amount_total_signed - inv.amount_residual_signed
                    _logger.info(f"    SO {order.name} - Invoice {inv.name} - Paid on this invoice (inv currency): {paid_on_this_invoice:.2f} {inv.currency_id.name}")

                    # Chuyển đổi sang tiền tệ của đơn hàng nếu cần
                    amount_to_add_in_order_currency = paid_on_this_invoice
                    if inv.currency_id != order.currency_id:
                        if not order.currency_id: # Xử lý trường hợp SO không có currency_id (hiếm)
                             _logger.error(f"    SO {order.name} - Invoice {inv.name} - ERROR: Sale Order currency is not set. Cannot convert.")
                             continue
                        try:
                            amount_to_add_in_order_currency = inv.currency_id._convert(
                                paid_on_this_invoice,
                                order.currency_id,
                                order.company_id or self.env.company, # Đảm bảo có company
                                inv.invoice_date or inv.date or fields.Date.context_today(order) # Ngày để lấy tỷ giá
                            )
                            _logger.info(f"    SO {order.name} - Invoice {inv.name} - Converted to order currency ({order.currency_id.name}): {amount_to_add_in_order_currency:.2f}")
                        except Exception as e:
                            _logger.error(f"    SO {order.name} - Invoice {inv.name} - Currency conversion error: {e}")
                            continue # Bỏ qua hóa đơn này nếu lỗi chuyển đổi
                    
                    paid_amount_in_order_currency += amount_to_add_in_order_currency
                    _logger.info(f"    SO {order.name} - Cumulative paid_amount_in_order_currency: {paid_amount_in_order_currency:.2f}")
                else:
                    _logger.info(f"    SO {order.name} - Invoice {inv.name} - Skipped (not 'posted' or not 'out_invoice'/'out_refund').")
            
            order.amount_paid = paid_amount_in_order_currency
            _logger.info(f"SO {order.name} (ID: {order.id}) - FINAL amount_paid set to: {order.amount_paid:.2f}")
        _logger.info(f"--- END COMPUTE: _compute_amount_paid for SOs: {self.mapped('name')} ---")


    @api.model
    def recompute_historical_amount_paid(self, domain=None, batch_size=100): # Giảm batch_size để dễ test
        _logger.info("--- ACTION: Starting recompute_historical_amount_paid ---")
        if domain is None:
            domain = []

        order_ids_to_recompute = self.search(domain).ids
        total_records = len(order_ids_to_recompute)
        _logger.info(f"Found {total_records} Sale Orders to recompute 'amount_paid'. Batch size: {batch_size}.")

        processed_count = 0
        for i in range(0, total_records, batch_size):
            batch_ids = order_ids_to_recompute[i:i + batch_size]
            _logger.info(f"Processing batch {i // batch_size + 1}/{(total_records + batch_size - 1) // batch_size + 1}: {len(batch_ids)} Order IDs")
            try:
                # Tạo môi trường mới cho mỗi lô để quản lý transaction tốt hơn
                with api.Environment.manage(), self.pool.cursor() as cr:
                    env_batch = api.Environment(cr, self.env.uid, self.env.context)
                    batch_orders = self.with_env(env_batch).browse(batch_ids)
                    
                    # Gọi trực tiếp phương thức compute
                    # Điều này sẽ ghi đè giá trị hiện tại nếu store=True
                    batch_orders._compute_amount_paid()
                    
                    env_batch.cr.commit() # Commit thay đổi của lô này
                    _logger.info(f"Batch starting with ID {batch_ids[0] if batch_ids else 'N/A'} committed successfully.")
            except Exception as e:
                self.env.cr.rollback() # Rollback nếu có lỗi trong lô
                _logger.error(f"Error recomputing 'amount_paid' for batch (first ID: {batch_ids[0] if batch_ids else 'N/A'}): {e}", exc_info=True)

            processed_count += len(batch_ids)
            _logger.info(f"Batch processed. Total processed so far: {processed_count}/{total_records}.")
        _logger.info("--- ACTION: Finished recompute_historical_amount_paid ---")
        return True
            
    @api.onchange('partner_id')
    def _onchange_partner_id_clear_installment_profile(self):
        # If customer changes, clear the installment profile as it's specific to old customer/order context
        if self.installment_profile_id and self.installment_profile_id.partner_id != self.partner_id:
            self.installment_profile_id = False

    def action_create_contract(self):
        # The logic to check for approved profile is good.
        for order in self:
            if not order.installment_profile_id or order.installment_profile_id.state != 'approved':
                raise UserError(_('Chỉ có thể tạo hợp đồng khi hồ sơ trả góp liên kết ở trạng thái Phê duyệt.'))
        # This should probably call the report on the profile, not the order,
        # as the contract details are on the profile.
        # However, your current report seems to be set up for sale.order, so let's assume that's intended for now.
        # If the report 'sale_installment.report_installment_contract' is designed for sale.order
        # and uses installment_profile_id to get details, this is fine.
        # Otherwise, it should be:
        # return self.env.ref('sale_installment.report_installment_contract_action').report_action(self.installment_profile_id)
        return self.env.ref('sale_installment.report_installment_contract').report_action(self)