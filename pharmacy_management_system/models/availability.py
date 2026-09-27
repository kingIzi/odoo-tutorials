# -- coding: utf-8 --

##############################################################################
#                                                                            #
# Part of WebbyCrown Solutions (Website: www.webbycrown.com).                #
# Copyright © 2025 WebbyCrown Solutions. All Rights Reserved.                #
#                                                                            #
# This module is developed and maintained by WebbyCrown Solutions.           #
# Unauthorized copying of this file, via any medium, is strictly prohibited. #
# Licensed under the terms of the WebbyCrown Solutions License Agreement.    #
#                                                                            #
##############################################################################

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PharmacyShiftTemplate(models.Model):
    _name = 'pharmacy.shift.template'
    _description = 'Pharmacy Shift Template'
    _check_company_auto = True

    name = fields.Char(required=True)
    resource_type = fields.Selection(
        [('pharmacist', 'Pharmacist'), ('technician', 'Technician')],
        default='pharmacist',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    weekday = fields.Selection(
        [
            ('0', 'Monday'),
            ('1', 'Tuesday'),
            ('2', 'Wednesday'),
            ('3', 'Thursday'),
            ('4', 'Friday'),
            ('5', 'Saturday'),
            ('6', 'Sunday'),
        ],
        string='Weekday',
        required=True,
    )
    start_time = fields.Float(string='Start Time')
    end_time = fields.Float(string='End Time')
    slot_duration = fields.Integer(string='Slot Duration (minutes)', default=30)
    capacity = fields.Integer(string='Capacity', default=1)
    telemedicine = fields.Boolean(string='Telemedicine')
    notes = fields.Text()


class PharmacyResourceAvailability(models.Model):
    _name = 'pharmacy.resource.availability'
    _description = 'Pharmacy Resource Availability'
    _order = 'date, start_time, id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    resource_type = fields.Selection(
        [('pharmacist', 'Pharmacist'), ('technician', 'Technician')],
        default='pharmacist',
        required=True,
    )
    user_id = fields.Many2one('res.users', string='Resource', required=True)
    pharmacy_id = fields.Many2one('pharmacy.pharmacy', required=True)
    company_id = fields.Many2one(
        'res.company',
        related='pharmacy_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    date = fields.Date(required=True)
    start_time = fields.Float(string='Start Time')
    end_time = fields.Float(string='End Time')
    slot_duration = fields.Integer(string='Slot Duration (minutes)', default=30)
    capacity = fields.Integer(string='Capacity', default=1)
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('completed', 'Completed'), ('cancelled', 'Cancelled')],
        default='draft',
    )
    notes = fields.Text()

    # Links
    shift_template_id = fields.Many2one(
        'pharmacy.shift.template',
        string='Shift Template',
        help='Select a shift template to auto-fill resource type, times, and capacity.',
    )

    @api.onchange('shift_template_id')
    def _onchange_shift_template_id(self):
        """Auto-fill fields from shift template."""
        if self.shift_template_id:
            self.resource_type = self.shift_template_id.resource_type
            self.start_time = self.shift_template_id.start_time
            self.end_time = self.shift_template_id.end_time
            self.slot_duration = self.shift_template_id.slot_duration
            self.capacity = self.shift_template_id.capacity

    @api.constrains('start_time', 'end_time')
    def _check_time_range(self):
        """Ensure end_time is greater than start_time."""
        for rec in self:
            if rec.start_time is not None and rec.end_time is not None:
                if rec.end_time <= rec.start_time:
                    raise ValidationError('End time must be greater than start time.')

    @api.depends('user_id', 'pharmacy_id', 'date', 'start_time', 'end_time')
    def _compute_name(self):
        for rec in self:
            parts = []
            if rec.user_id:
                parts.append(rec.user_id.name)
            if rec.pharmacy_id:
                parts.append(rec.pharmacy_id.name)
            if rec.date:
                parts.append(rec.date.strftime('%Y-%m-%d'))
            if rec.start_time or rec.end_time:
                parts.append('%s-%s' % (rec.start_time or 0, rec.end_time or ''))
            rec.name = ' / '.join(str(p) for p in parts if p)

    @api.constrains('user_id', 'pharmacy_id', 'date', 'start_time', 'end_time', 'state')
    def _check_overlap(self):
        for rec in self:
            if rec.state != 'published':
                continue
            if not (rec.date and rec.start_time is not None and rec.end_time is not None):
                continue
            domain = [
                ('id', '!=', rec.id),
                ('user_id', '=', rec.user_id.id),
                ('pharmacy_id', '=', rec.pharmacy_id.id),
                ('state', '=', 'published'),
                ('date', '=', rec.date),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    'Overlapping published availability slots are not allowed for the same resource and pharmacy.'
                )


