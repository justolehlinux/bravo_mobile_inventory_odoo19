from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BravoInventorySession(models.Model):
    _name = 'bravo.inventory.session'
    _description = 'Bravo Mobile Inventory Session'
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, readonly=True, copy=False, default=lambda self: _('New'))
    user_id = fields.Many2one(
        'res.users', required=True, readonly=True, default=lambda self: self.env.user,
        string='Counter', index=True,
    )
    location_id = fields.Many2one(
        'stock.location', required=True, readonly=True, index=True,
        domain=[('usage', '=', 'internal')], string='Exact Count Location',
        help='MVP counts exactly this internal location, not its children.',
    )
    state = fields.Selection([
        ('draft', 'Counting'),
        ('review', 'Review'),
        ('applied', 'Applied'),
        ('cancelled', 'Cancelled'),
    ], required=True, default='draft', readonly=True, index=True)
    line_ids = fields.One2many('bravo.inventory.line', 'session_id', string='Count Lines')
    applied_at = fields.Datetime(readonly=True)
    applied_by_id = fields.Many2one('res.users', readonly=True)

    line_count = fields.Integer(compute='_compute_totals')
    changed_count = fields.Integer(compute='_compute_totals')
    barcode_bound_count = fields.Integer(compute='_compute_totals')

    @api.depends('line_ids', 'line_ids.state', 'line_ids.difference_qty', 'line_ids.barcode_bound_during_session')
    def _compute_totals(self):
        for session in self:
            confirmed = session.line_ids.filtered(lambda line: line.state == 'confirmed')
            session.line_count = len(confirmed)
            session.changed_count = len(confirmed.filtered(lambda line: line.difference_qty != 0))
            session.barcode_bound_count = len(session.line_ids.filtered('barcode_bound_during_session'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bravo.inventory.session') or _('New')
        return super().create(vals_list)

    def action_open_mobile(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/mobile/inventory',
            'target': 'self',
        }

    def action_cancel(self):
        for session in self:
            if session.state == 'applied':
                raise UserError(_('An applied session cannot be cancelled.'))
            session.state = 'cancelled'
        return True
