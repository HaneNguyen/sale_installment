from odoo import http
from odoo.http import request

class SaleInstallmentController(http.Controller):
    @http.route('/installment/profile/approve/<int:profile_id>', type='http', auth='user')
    def approve_profile(self, profile_id, **kwargs):
        profile = request.env['sale.installment.profile'].browse(profile_id)
        if profile.exists():
            profile.action_approve()
        return request.redirect('/web?#id=%d&model=sale.installment.profile&view_type=form' % profile_id)

    @http.route('/installment/profile/reject/<int:profile_id>', type='http', auth='user')
    def reject_profile(self, profile_id, **kwargs):
        profile = request.env['sale.installment.profile'].browse(profile_id)
        if profile.exists():
            profile.action_reject()
        return request.redirect('/web?#id=%d&model=sale.installment.profile&view_type=form' % profile_id)