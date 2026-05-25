from odoo import api, fields, models


class BravoInventoryLine(models.Model):
    _name = 'bravo.inventory.line'
    _description = 'Bravo Mobile Inventory Line'
    _order = 'write_date desc, id desc'

    session_id = fields.Many2one('bravo.inventory.session', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', index=True)
    barcode = fields.Char(required=True, index=True)
    product_name = fields.Char(readonly=True)
    category_id = fields.Many2one('product.category', readonly=True)
    uom_id = fields.Many2one('uom.uom', readonly=True)
    theoretical_qty = fields.Float(readonly=True, digits='Product Unit')
    counted_qty = fields.Float(digits='Product Unit')
    difference_qty = fields.Float(compute='_compute_difference_qty', store=True, digits='Product Unit')
    scan_status = fields.Selection([
        ('found', 'Found'),
        ('not_found', 'Not Found'),
        ('bound', 'Barcode Bound During Count'),
        ('unsupported', 'Unsupported'),
    ], required=True, default='found', index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('skipped', 'Skipped'),
    ], required=True, default='draft', index=True)
    note = fields.Text()
    barcode_bound_during_session = fields.Boolean(default=False, readonly=True)
    barcode_bound_by_id = fields.Many2one('res.users', readonly=True)
    barcode_bound_at = fields.Datetime(readonly=True)

    _session_barcode_unique = models.Constraint(
        'UNIQUE(session_id, barcode)',
        'This barcode is already present in this session.',
    )
    _session_product_unique = models.Constraint(
        'UNIQUE(session_id, product_id)',
        'This product is already present in this session.',
    )

    @api.depends('theoretical_qty', 'counted_qty', 'state')
    def _compute_difference_qty(self):
        for line in self:
            line.difference_qty = (
                line.counted_qty - line.theoretical_qty
                if line.state == 'confirmed' and line.product_id else 0.0
            )
