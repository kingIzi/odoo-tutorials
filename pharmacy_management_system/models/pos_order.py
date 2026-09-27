# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

from odoo import models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _generate_order_invoice(self):
        """Pharmacy sales: generate the invoice automatically whenever a
        customer (patient) is set on the order, instead of requiring the
        cashier to press the Invoice button or the customer to be a company.
        """
        for order in self:
            if order.partner_id and not order.to_invoice:
                order.to_invoice = True
        return super()._generate_order_invoice()
