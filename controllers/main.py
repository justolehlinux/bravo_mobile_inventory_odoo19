from odoo import fields, http, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools.float_utils import float_compare


class BravoMobileInventoryController(http.Controller):

    # ---------- Page ----------

    @http.route('/mobile/inventory', type='http', auth='user', methods=['GET'])
    def mobile_inventory_page(self, **kwargs):
        self._require_stock_user()
        locations = request.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('company_id', 'in', [False, request.env.company.id]),
        ], order='complete_name')
        return request.render('bravo_mobile_inventory.mobile_inventory_page', {
            'locations': locations,
            'can_bind': request.env.user.has_group(
                'bravo_mobile_inventory.group_bravo_inventory_barcode_binder'
            ),
            'can_apply': request.env.user.has_group('stock.group_stock_manager'),
        })

    # ---------- Helpers ----------

    def _require_stock_user(self):
        if not request.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_('You do not have access to mobile inventory.'))

    def _require_binder(self):
        self._require_stock_user()
        if not request.env.user.has_group(
            'bravo_mobile_inventory.group_bravo_inventory_barcode_binder'
        ):
            raise AccessError(_('You do not have permission to bind product barcodes.'))

    def _require_manager(self):
        if not request.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Only an inventory manager can apply stock adjustments.'))

    def _get_session(self, session_id, allowed_states=None):
        self._require_stock_user()
        session = request.env['bravo.inventory.session'].browse(int(session_id or 0)).exists()
        if not session:
            raise UserError(_('Inventory session not found.'))
        is_manager = request.env.user.has_group('stock.group_stock_manager')
        if session.user_id != request.env.user and not is_manager:
            raise AccessError(_('You can only open your own inventory sessions.'))
        if allowed_states and session.state not in allowed_states:
            raise UserError(_('The inventory session is no longer editable.'))
        return session

    def _qty(self, product, location):
        # Deliberately strict: this MVP counts one exact stock location only.
        return product.with_context(location=location.id, strict=True).qty_available

    def _product_payload(self, product):
        return {
            'id': product.id,
            'name': product.display_name,
            'barcode': product.barcode or '',
            'category': product.categ_id.display_name or '',
            'uom': product.uom_id.display_name or '',
        }

    def _line_payload(self, line):
        return {
            'id': line.id,
            'barcode': line.barcode,
            'product_id': line.product_id.id or False,
            'product_name': line.product_name or line.product_id.display_name or '',
            'category': line.category_id.display_name or '',
            'uom': line.uom_id.display_name or '',
            'theoretical_qty': line.theoretical_qty,
            'counted_qty': line.counted_qty if line.state == 'confirmed' else None,
            'difference_qty': line.difference_qty,
            'scan_status': line.scan_status,
            'state': line.state,
            'barcode_bound': line.barcode_bound_during_session,
        }

    def _validated_product(self, product):
        if not product.is_storable:
            return _('This product is not stockable and cannot be counted.')
        if product.tracking != 'none':
            return _('Products tracked by lot or serial number are not supported in this version.')
        return False

    def _get_quant_snapshot(self, session, line):
        Quant = request.env['stock.quant']
        quants = Quant.search([
            ('product_id', '=', line.product_id.id),
            ('location_id', '=', session.location_id.id),
        ])
        detailed = quants.filtered(lambda q: q.lot_id or q.package_id or q.owner_id)
        if detailed:
            return {
                'blocked': True,
                'reason': _('Stock exists in lot/package/owner-specific quants; this version cannot adjust it safely.'),
                'current_qty': sum(quants.mapped('quantity')),
                'quant': False,
            }
        base_quants = quants.filtered(lambda q: not q.lot_id and not q.package_id and not q.owner_id)
        if len(base_quants) > 1:
            return {
                'blocked': True,
                'reason': _('More than one base quant exists for this product and location.'),
                'current_qty': sum(quants.mapped('quantity')),
                'quant': False,
            }
        return {
            'blocked': False,
            'reason': '',
            'current_qty': sum(quants.mapped('quantity')),
            'quant': base_quants[:1],
        }

    def _summary_payload(self, session):
        confirmed = session.line_ids.filtered(lambda l: l.state == 'confirmed' and l.product_id)
        missing = session.line_ids.filtered(lambda l: l.scan_status == 'not_found' and l.state == 'skipped')
        unsupported = session.line_ids.filtered(lambda l: l.scan_status == 'unsupported')
        return {
            'session_id': session.id,
            'session_name': session.name,
            'location': session.location_id.complete_name,
            'state': session.state,
            'total': len(confirmed),
            'unchanged': len(confirmed.filtered(lambda l: l.difference_qty == 0)),
            'shortage': len(confirmed.filtered(lambda l: l.difference_qty < 0)),
            'surplus': len(confirmed.filtered(lambda l: l.difference_qty > 0)),
            'not_found': len(missing),
            'unsupported': len(unsupported),
            'barcode_bound': len(session.line_ids.filtered('barcode_bound_during_session')),
            'lines': [self._line_payload(line) for line in confirmed.sorted('product_name')],
            'bound_lines': [self._line_payload(line) for line in session.line_ids.filtered('barcode_bound_during_session')],
        }

    def _preview_payload(self, session):
        rows = []
        has_blocker = False
        for line in session.line_ids.filtered(lambda l: l.state == 'confirmed' and l.product_id):
            snap = self._get_quant_snapshot(session, line)
            precision = line.uom_id.rounding or 0.01
            conflict = not snap['blocked'] and float_compare(
                snap['current_qty'], line.theoretical_qty, precision_rounding=precision
            ) != 0
            blocked = snap['blocked'] or conflict
            has_blocker = has_blocker or blocked
            rows.append({
                'line_id': line.id,
                'product_name': line.product_name,
                'barcode': line.barcode,
                'scanned_qty': line.theoretical_qty,
                'current_qty': snap['current_qty'],
                'counted_qty': line.counted_qty,
                'difference_from_current': line.counted_qty - snap['current_qty'],
                'blocked': blocked,
                'conflict': conflict,
                'message': snap['reason'] if snap['blocked'] else (
                    _('Quantity changed in Odoo after the first scan.') if conflict else ''
                ),
            })
        return {'can_apply': bool(rows) and not has_blocker, 'rows': rows}

    # ---------- JSON-RPC API ----------

    @http.route('/mobile/inventory/start', type='jsonrpc', auth='user', methods=['POST'])
    def start(self, location_id):
        self._require_stock_user()
        location = request.env['stock.location'].browse(int(location_id or 0)).exists()
        if not location or location.usage != 'internal':
            raise UserError(_('Choose an internal stock location.'))
        if location.company_id and location.company_id != request.env.company:
            raise UserError(_('This location belongs to another company.'))
        session = request.env['bravo.inventory.session'].create({'location_id': location.id})
        return {
            'success': True,
            'session_id': session.id,
            'name': session.name,
            'location': session.location_id.complete_name,
        }

    @http.route('/mobile/inventory/scan', type='jsonrpc', auth='user', methods=['POST'])
    def scan(self, session_id, barcode):
        session = self._get_session(session_id, ['draft'])
        barcode = (barcode or '').strip()
        if not barcode:
            return {'success': False, 'error': 'empty_barcode', 'message': _('Scan a barcode first.')}

        products = request.env['product.product'].search([('barcode', '=', barcode)], limit=2)
        if len(products) > 1:
            return {'success': False, 'error': 'duplicate_barcode', 'message': _('Multiple products have this barcode. Fix the catalogue before counting.')}

        line = session.line_ids.filtered(lambda l: l.barcode == barcode)[:1]
        if not products:
            if not line:
                line = request.env['bravo.inventory.line'].create({
                    'session_id': session.id,
                    'barcode': barcode,
                    'scan_status': 'not_found',
                    'state': 'draft',
                })
            return {
                'success': True,
                'status': 'not_found',
                'line': self._line_payload(line),
                'can_bind': request.env.user.has_group('bravo_mobile_inventory.group_bravo_inventory_barcode_binder'),
                'message': _('Barcode not found.'),
            }

        product = products[0]
        problem = self._validated_product(product)
        existing_product_line = session.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if existing_product_line:
            return {
                'success': True,
                'status': 'found',
                'existing': True,
                'line': self._line_payload(existing_product_line),
                'product': self._product_payload(product),
            }

        if problem:
            if not line:
                line = request.env['bravo.inventory.line'].create({
                    'session_id': session.id,
                    'product_id': product.id,
                    'barcode': barcode,
                    'product_name': product.display_name,
                    'category_id': product.categ_id.id,
                    'uom_id': product.uom_id.id,
                    'scan_status': 'unsupported',
                    'state': 'draft',
                    'note': problem,
                })
            return {'success': True, 'status': 'unsupported', 'line': self._line_payload(line), 'message': problem}

        values = {
            'product_id': product.id,
            'barcode': barcode,
            'product_name': product.display_name,
            'category_id': product.categ_id.id,
            'uom_id': product.uom_id.id,
            'theoretical_qty': self._qty(product, session.location_id),
            'scan_status': 'found',
            'state': 'draft',
        }
        if line:
            line.write(values)
        else:
            values['session_id'] = session.id
            line = request.env['bravo.inventory.line'].create(values)
        return {
            'success': True,
            'status': 'found',
            'existing': False,
            'line': self._line_payload(line),
            'product': self._product_payload(product),
        }

    @http.route('/mobile/inventory/search_product', type='jsonrpc', auth='user', methods=['POST'])
    def search_product(self, query):
        self._require_binder()
        query = (query or '').strip()
        if len(query) < 2:
            return {'products': []}
        products = request.env['product.product'].search([
            ('is_storable', '=', True),
            '|', ('name', 'ilike', query), ('default_code', 'ilike', query),
        ], limit=20)
        return {'products': [{
            **self._product_payload(product),
            'tracking': product.tracking,
            'can_bind_barcode': not product.barcode and product.tracking == 'none',
        } for product in products]}

    @http.route('/mobile/inventory/bind_barcode', type='jsonrpc', auth='user', methods=['POST'])
    def bind_barcode(self, session_id, barcode, product_id):
        self._require_binder()
        session = self._get_session(session_id, ['draft'])
        barcode = (barcode or '').strip()
        product = request.env['product.product'].browse(int(product_id or 0)).exists()
        if not barcode or not product:
            return {'success': False, 'error': 'invalid_binding', 'message': _('Barcode or product is missing.')}
        problem = self._validated_product(product)
        if problem:
            return {'success': False, 'error': 'unsupported_product', 'message': problem}

        assigned = request.env['product.product'].sudo().search([('barcode', '=', barcode)], limit=1)
        if assigned and assigned != product:
            return {
                'success': False,
                'error': 'barcode_already_assigned',
                'message': _('This barcode has already been assigned to another product.'),
                'assigned_product': self._product_payload(assigned),
            }
        if product.barcode and product.barcode != barcode:
            return {
                'success': False,
                'error': 'product_already_has_barcode',
                'message': _('The selected product already has another barcode. Replacing it is prohibited here.'),
                'existing_barcode': product.barcode,
            }

        line = session.line_ids.filtered(lambda l: l.barcode == barcode)[:1]
        product_line = session.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if product_line and product_line != line:
            return {
                'success': False,
                'error': 'product_already_counted',
                'message': _('This product is already present in the count session.'),
                'line': self._line_payload(product_line),
            }

        try:
            if not product.barcode:
                # The dedicated binder group authorizes this limited sudo write.
                product.sudo().write({'barcode': barcode})
        except (UserError, ValidationError) as exc:
            return {'success': False, 'error': 'barcode_write_failed', 'message': str(exc)}

        vals = {
            'product_id': product.id,
            'product_name': product.display_name,
            'category_id': product.categ_id.id,
            'uom_id': product.uom_id.id,
            'theoretical_qty': self._qty(product, session.location_id),
            'scan_status': 'bound',
            'state': 'draft',
            'barcode_bound_during_session': True,
            'barcode_bound_by_id': request.env.user.id,
            'barcode_bound_at': fields.Datetime.now(),
        }
        if line:
            line.write(vals)
        else:
            vals.update({'session_id': session.id, 'barcode': barcode})
            line = request.env['bravo.inventory.line'].create(vals)
        return {
            'success': True,
            'status': 'bound',
            'line': self._line_payload(line),
            'product': self._product_payload(product),
        }

    @http.route('/mobile/inventory/set_qty', type='jsonrpc', auth='user', methods=['POST'])
    def set_qty(self, session_id, line_id, counted_qty=None):
        session = self._get_session(session_id, ['draft'])
        line = request.env['bravo.inventory.line'].browse(int(line_id or 0)).exists()
        if not line or line.session_id != session or not line.product_id:
            raise UserError(_('Count line not found.'))
        if line.scan_status == 'unsupported':
            raise UserError(_('Unsupported products cannot be counted in this version.'))
        qty = line.theoretical_qty if counted_qty in (None, '') else float(counted_qty)
        if qty < 0:
            return {'success': False, 'error': 'negative_qty', 'message': _('Physical quantity cannot be negative.')}
        line.write({'counted_qty': qty, 'state': 'confirmed'})
        return {'success': True, 'line': self._line_payload(line)}

    @http.route('/mobile/inventory/skip', type='jsonrpc', auth='user', methods=['POST'])
    def skip(self, session_id, line_id):
        session = self._get_session(session_id, ['draft'])
        line = request.env['bravo.inventory.line'].browse(int(line_id or 0)).exists()
        if not line or line.session_id != session:
            raise UserError(_('Count line not found.'))
        line.write({'state': 'skipped'})
        return {'success': True, 'line': self._line_payload(line)}

    @http.route('/mobile/inventory/finish', type='jsonrpc', auth='user', methods=['POST'])
    def finish(self, session_id):
        session = self._get_session(session_id, ['draft'])
        unresolved = session.line_ids.filtered(lambda l: l.state == 'draft')
        if unresolved:
            return {
                'success': False,
                'error': 'unresolved_lines',
                'message': _('There are scanned items without a saved quantity or Skip decision.'),
                'unresolved': [self._line_payload(line) for line in unresolved],
            }
        if not session.line_ids.filtered(lambda l: l.state == 'confirmed'):
            return {'success': False, 'error': 'empty_count', 'message': _('No products were counted.')}
        session.state = 'review'
        return {'success': True, 'summary': self._summary_payload(session)}

    @http.route('/mobile/inventory/reopen', type='jsonrpc', auth='user', methods=['POST'])
    def reopen(self, session_id):
        session = self._get_session(session_id, ['review'])
        session.state = 'draft'
        return {'success': True}

    @http.route('/mobile/inventory/review', type='jsonrpc', auth='user', methods=['POST'])
    def review(self, session_id):
        session = self._get_session(session_id, ['draft', 'review', 'applied'])
        return {'success': True, 'summary': self._summary_payload(session)}

    @http.route('/mobile/inventory/preview_apply', type='jsonrpc', auth='user', methods=['POST'])
    def preview_apply(self, session_id):
        session = self._get_session(session_id, ['review'])
        return {'success': True, 'preview': self._preview_payload(session)}

    @http.route('/mobile/inventory/apply', type='jsonrpc', auth='user', methods=['POST'])
    def apply(self, session_id):
        self._require_manager()
        session = self._get_session(session_id, ['review'])
        preview = self._preview_payload(session)
        if not preview['can_apply']:
            return {'success': False, 'error': 'blocked', 'message': _('Application is blocked. Resolve quantity conflicts first.'), 'preview': preview}

        Quant = request.env['stock.quant'].with_context(inventory_mode=True)
        quants_to_apply = request.env['stock.quant']
        for line in session.line_ids.filtered(lambda l: l.state == 'confirmed' and l.product_id):
            snap = self._get_quant_snapshot(session, line)
            if snap['quant']:
                quant = snap['quant'].with_context(inventory_mode=True)
                quant.write({'inventory_quantity': line.counted_qty, 'user_id': request.env.user.id})
            else:
                quant = Quant.create({
                    'product_id': line.product_id.id,
                    'location_id': session.location_id.id,
                    'inventory_quantity': line.counted_qty,
                    'user_id': request.env.user.id,
                })
            quants_to_apply |= quant

        result = quants_to_apply.with_context(inventory_mode=True).action_apply_inventory()
        if result and result.get('res_model') == 'stock.inventory.conflict':
            quants_to_apply.with_context(inventory_mode=True).action_clear_inventory_quantity()
            return {
                'success': False,
                'error': 'concurrent_conflict',
                'message': _('Stock moved while the adjustment was being applied. Nothing was applied; run preview again.'),
            }
        session.write({
            'state': 'applied',
            'applied_at': fields.Datetime.now(),
            'applied_by_id': request.env.user.id,
        })
        return {'success': True, 'summary': self._summary_payload(session)}

    @http.route('/mobile/inventory/cancel', type='jsonrpc', auth='user', methods=['POST'])
    def cancel(self, session_id):
        session = self._get_session(session_id, ['draft', 'review'])
        session.state = 'cancelled'
        return {'success': True}
