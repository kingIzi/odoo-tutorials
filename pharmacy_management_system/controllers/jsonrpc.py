# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
##############################################################################

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PharmacyJsonRPCController(http.Controller):

    def _jsonrpc_result(self, payload, result):
        return {
            'jsonrpc': '2.0',
            'id': payload.get('id'),
            'result': result,
        }

    def _jsonrpc_error(self, payload, message):
        _logger.warning("JSON-RPC error: %s", message)
        return {
            'jsonrpc': '2.0',
            'id': payload.get('id'),
            'error': {
                'code': 400,
                'message': message,
            },
        }

    @http.route('/pharmacy/jsonrpc/availability', type='jsonrpc', auth='user', csrf=False, methods=['POST'])
    def rpc_availability(self, **payload):
        """JSON-RPC endpoint for staff availability queries."""
        params = payload.get('params', {}) if isinstance(payload, dict) else {}
        pharmacy_code = params.get('pharmacy_code')
        user_id = params.get('user_id')
        date_from = params.get('date_from')
        date_to = params.get('date_to')

        domain = [('state', '=', 'published')]
        if pharmacy_code:
            pharmacy = request.env['pharmacy.pharmacy'].sudo().search([('code', '=', pharmacy_code)], limit=1)
            if pharmacy:
                domain.append(('pharmacy_id', '=', pharmacy.id))
        if user_id:
            domain.append(('user_id', '=', user_id))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))

        availabilities = request.env['pharmacy.resource.availability'].sudo().search(domain)
        result = [
            {
                'id': av.id,
                'user': av.user_id.name if av.user_id else False,
                'pharmacy': av.pharmacy_id.name if av.pharmacy_id else False,
                'date': av.date.isoformat() if av.date else False,
                'start_time': av.start_time,
                'end_time': av.end_time,
                'capacity': av.capacity,
            }
            for av in availabilities
        ]
        return self._jsonrpc_result(payload, result)
