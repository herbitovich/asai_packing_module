from odoo import models, fields, api
from datetime import date
import logging

logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)


class PackingOrder(models.Model):
    _name = "packing.order"
    _description = "Packing Order"

    name = fields.Char("Order Reference", required=True)
    operator_id = fields.Many2one("res.users", string="Operator")
    date = fields.Date("Date", default=fields.Date.today)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
            ("defective", "Defective"),
        ],
        string="Status",
        default="draft",
    )
    details_ids = fields.One2many("packing.detail", "order_id", string="Details")
    shipping_label = fields.Binary("Shipping Label")

    def write(self, vals):
        result = super(PackingOrder, self).write(vals)
        for order in self:
            if order.operator_id:
                order._update_analytics()
        return result

    def _update_analytics(self):
        analytic = self.env['packing.analytics'].search([
            ('operator_id', '=', self.operator_id.id),
            ('date', '=', self.date)
        ], limit=1)
        
        if not analytic:
            analytic = self.env['packing.analytics'].create({
                'operator_id': self.operator_id.id,
                'date': self.date
            })
        
        orders = self.search([
            ('operator_id', '=', self.operator_id.id),
            ('date', '=', self.date)
        ])
        
        total_orders = len(orders)
        logging.critical("hey im here")
        logging.critical(f'{[order.details_ids.mapped('quantity') for order in orders]}')
        total_details = sum(sum(order.details_ids.mapped('packed_quantity')) for order in orders)
        logging.critical("im even here bro")
        defective_details = sum(sum(order.details_ids.mapped('defective_quantity')) for order in orders)
        logging.critical("im even here bro!!")
        defective_orders = len(orders.filtered(lambda o: o.state == 'defective'))
        
        analytic.write({
            'total_orders': total_orders,
            'total_details': total_details,
            'defective_details': defective_details,
            'defective_orders': defective_orders
        })


class PackingDetail(models.Model):
    _name = "packing.detail"
    _description = "Packing Detail"

    name = fields.Char("Detail Name", required=True)
    detail_id = fields.Char("Detail ID")
    order_id = fields.Many2one("packing.order", string="Order", ondelete="cascade")
    quantity = fields.Integer("Quantity", default=1)
    packed_quantity = fields.Integer("Packed Quantity", default=0)
    defective_quantity = fields.Integer("Defective Quantity", default=0)
    size_measurements = fields.Char("Size Measurements")
    is_packed = fields.Boolean("Packed", compute="_compute_is_packed")
    is_defective = fields.Boolean("Defective", compute="_compute_is_defective")

    @api.depends('packed_quantity', 'quantity')
    def _compute_is_packed(self):
        for record in self:
            record.is_packed = record.packed_quantity >= record.quantity

    @api.depends('defective_quantity')
    def _compute_is_defective(self):
        for record in self:
            record.is_defective = record.defective_quantity > 0

    def write(self, vals):
        result = super(PackingDetail, self).write(vals)
        for detail in self:
            if detail.order_id.operator_id:
                detail.order_id._update_analytics()
        return result


class DefectiveDetail(models.Model):
    _name = "defective.detail"
    _description = "Defective Detail"

    detail_id = fields.Many2one('packing.detail', string="Detail")
    order_id = fields.Many2one('packing.order', string="Order")
    quantity = fields.Integer("Defective Quantity")
    replaced = fields.Boolean("Replaced", default=False)


class PackingAnalytics(models.Model):
    _name = "packing.analytics"
    _description = "Packing Analytics"

    operator_id = fields.Many2one("res.users", string="Operator")
    date = fields.Date("Date", default=fields.Date.today)
    total_orders = fields.Integer("Total Orders", default=0)
    total_details = fields.Integer("Total Details", default=0)
    defective_details = fields.Integer("Defective Details", default=0)
    defective_orders = fields.Integer("Defective Orders", default=0)