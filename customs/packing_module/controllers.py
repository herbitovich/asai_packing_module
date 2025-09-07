import csv
import base64
from io import StringIO
from odoo import http, fields
from odoo.http import request
from reportlab.pdfgen import canvas
from io import BytesIO
import logging

logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)

class PackingController(http.Controller):
    @http.route('/packing/orders', auth='user', website=True)
    def packing_orders(self, **kwargs):
        orders = request.env['packing.order'].search([('state', 'in', ['draft', 'done'])])
        return request.render('packing_module.packing_orders_page', {
            'orders': orders,
            'error': kwargs.get('error')
        })

    @http.route('/packing/defective_orders', auth='user', website=True)
    def defective_orders(self):
        defective_orders = request.env['packing.order'].search([('state', '=', 'defective')])
        return request.render('packing_module.defective_orders_page', {
            'defective_orders': defective_orders
        })

    @http.route('/packing/analytics', auth='user', website=True)
    def analytics(self):
        analytics = request.env['packing.analytics'].search([])
        return request.render('packing_module.analytics_page', {
            'analytics': analytics
        })

    @http.route('/packing/order/<int:order_id>', type='http', auth='user', website=True)
    def order_packing(self, order_id, **kwargs):
        order = request.env['packing.order'].sudo().browse(order_id)
        return request.render('packing_module.packing_order_page', {
            'order': order,
            'details': order.details_ids
        })

    #Загрузка и парсинг CSV
    @http.route('/packing/upload_csv', type='http', auth='user', website=True, csrf=False)
    def upload_csv(self, csv_file, **kwargs):
        logging.critical('Started CSV upload')
        if csv_file:
            try:
                logging.info('CSV file received')
                csv_data = csv_file.read().decode('utf-8')
                csv_file = StringIO(csv_data)
                csv_reader = csv.DictReader(csv_file, delimiter=',')
                logging.info('CSV parsed successfully')
                
                for row in csv_reader:
                    logging.info(f'Processing row: {row}')
                    order = request.env['packing.order'].sudo().search([
                        ('name', '=', row['order_id'])
                    ], limit=1)
                    
                    if not order:
                        logging.info(f'Creating new order: {row["order_id"]}')
                        order = request.env['packing.order'].sudo().create({
                            'name': row['order_id'],
                            'state': 'draft'
                        })
                        logging.info(f'Order created: {order.id}')
                    
                    logging.info(f'Creating detail for order: {order.id}')
                    request.env['packing.detail'].sudo().create({
                        'detail_id': row['detail_id'],
                        'name': row['name'],
                        'order_id': order.id,
                        'quantity': int(row['quantity']),
                        'size_measurements': row['size_measurements']
                    })
                    logging.info('Detail created successfully')
                
                return request.redirect('/packing/orders')
            except Exception as e:
                logging.error(f'Error parsing CSV: {str(e)}')
                return request.redirect('/packing/orders?error=parse_error')
        logging.warning('No file provided for upload')
        return request.redirect('/packing/orders?error=no_file')

    #Упаковка детали
    @http.route('/packing/pack_detail', type='json', auth='user', methods=['POST'], csrf=False)
    def pack_detail(self, **kwargs):
        try:
            data = request.get_json_data()
            detail_id = data.get('detail_id')
            if not detail_id:
                return {'error': 'Missing detail_id'}
            
            detail = request.env['packing.detail'].sudo().browse(int(detail_id))
            detail.packed_quantity += 1
            
            order = detail.order_id
            all_packed = all(d.packed_quantity >= d.quantity for d in order.details_ids)
            
            if all_packed:
                order.state = 'done'
                label_data = self.generate_shipping_label(order)
                order.shipping_label = label_data
            
            if order.operator_id:
                order._update_analytics()
            
            return {
                'packed_quantity': detail.packed_quantity,
                'is_packed': detail.packed_quantity >= detail.quantity,
                'order_completed': all_packed
            }
        except Exception as e:
            logging.error(f'Error in pack_detail: {str(e)}')
            return {'error': str(e)}

    #Брак
    @http.route('/packing/mark_defective', type='json', auth='user', methods=['POST'], csrf=False)
    def mark_defective(self, **kwargs):
        try:
            data = request.get_json_data()
            detail_id = data.get('detail_id')
            quantity = data.get('quantity')
            
            if not detail_id or not quantity:
                return {'error': 'Missing detail_id or quantity'}
            
            detail = request.env['packing.detail'].sudo().browse(int(detail_id))
            detail.defective_quantity += int(quantity)
            
            if detail.defective_quantity > 0:
                detail.order_id.state = 'defective'
            
            if detail.order_id.operator_id:
                detail.order_id._update_analytics()
            
            return {
                'defective_quantity': detail.defective_quantity,
                'is_defective': detail.defective_quantity > 0
            }
        except Exception as e:
            logging.error(f'Error in mark_defective: {str(e)}')
            return {'error': str(e)}

    @http.route('/packing/reset_order', type='json', auth='user', methods=['POST'], csrf=False)
    def reset_order(self, **kwargs):
        try:
            data = request.get_json_data()
            order_id = data.get('order_id')
            
            if not order_id:
                return {'error': 'Missing order_id'}
            
            order = request.env['packing.order'].sudo().browse(int(order_id))
            for detail in order.details_ids:
                detail.packed_quantity = 0
                detail.defective_quantity = 0
            order.state = 'draft'
            
            if order.operator_id:
                order._update_analytics()
            
            return {'success': True}
        except Exception as e:
            logging.error(f'Error in reset_order: {str(e)}')
            return {'error': str(e)}

    @http.route('/packing/mark_replaced', type='json', auth='user', methods=['POST'], csrf=False)
    def mark_replaced(self, **kwargs):
        try:
            data = request.get_json_data()
            detail_id = data.get('detail_id')
            
            if not detail_id:
                return {'error': 'Missing detail_id'}
            
            detail = request.env['packing.detail'].sudo().browse(int(detail_id))
            detail.defective_quantity = 0
            
            order = detail.order_id
            has_defects = any(d.defective_quantity > 0 for d in order.details_ids)
            
            if not has_defects:
                order.state = 'draft'
            
            if order.operator_id:
                order._update_analytics()
            
            return {
                'defective_quantity': detail.defective_quantity,
                'order_fixed': not has_defects
            }
        except Exception as e:
            logging.error(f'Error in mark_replaced: {str(e)}')
            return {'error': str(e)}

    #Устанавливаем оператора заказа
    @http.route('/packing/set_operator', type='json', auth='user', methods=['POST'], csrf=False)
    def set_operator(self, **kwargs):
        try:
            data = request.get_json_data()
            order_id = data.get('order_id')
            operator_id = data.get('operator_id')
            
            if not order_id or not operator_id:
                return {'error': 'Missing order_id or operator_id'}
            
            order = request.env['packing.order'].sudo().browse(int(order_id))
            order.operator_id = int(operator_id)
            
            order._update_analytics()
            
            return {'success': True}
        except Exception as e:
            logging.error(f'Error in set_operator: {str(e)}')
            return {'error': str(e)}

    #Рисуем транспортную этикетку
    def generate_shipping_label(self, order):
        buffer = BytesIO()
        p = canvas.Canvas(buffer)
        
        p.setFont("Helvetica-Bold", 16)
        p.drawString(100, 800, "SHIPPING LABEL")
        
        p.setFont("Helvetica", 12)
        p.drawString(100, 770, f"Order: {order.name}")
        p.drawString(100, 750, f"Date: {fields.Datetime.now()}")
        
        if order.operator_id:
            p.drawString(100, 730, f"Operator: {order.operator_id.name}")
        
        p.drawString(100, 700, "Barcode: [0000000000]")
        
        p.line(100, 680, 400, 680)
        
        p.drawString(100, 660, "Contents:")
        y_position = 640
        
        for detail in order.details_ids:
            p.drawString(120, y_position, f"- {detail.name} (x{detail.quantity})")
            y_position -= 20
            if y_position < 100:
                p.showPage()
                y_position = 800
        
        p.drawString(100, 200, "Sender signature: ___________________")
        p.drawString(100, 180, "Shipment date: ___________________")
        
        p.showPage()
        p.save()
        
        buffer.seek(0)
        return base64.b64encode(buffer.read())
    
    @http.route('/packing/quick_pack_detail', type='json', auth='user', methods=['POST'], csrf=False)
    def quick_pack_detail(self, **kwargs):
        try:
            data = request.get_json_data()
            detail_code = data.get('detail_code')
            order_id = data.get('order_id')
            
            if not detail_code or not order_id:
                return {'error': 'Отсутствует ID детали или заказа'}
            
            detail = request.env['packing.detail'].sudo().search([
                ('detail_id', '=', detail_code),
                ('order_id', '=', int(order_id))
            ], limit=1)
            
            if not detail:
                return {'error': 'Деталь с таким ID не найдена в этом заказе'}
            
            if detail.packed_quantity >= detail.quantity:
                return {'error': 'Все детали этого типа уже упакованы'}
            
            detail.packed_quantity += 1
            
            order = detail.order_id
            all_packed = all(d.packed_quantity >= d.quantity for d in order.details_ids)
            
            if all_packed:
                order.state = 'done'
                label_data = self.generate_shipping_label(order)
                order.shipping_label = label_data
            
            if order.operator_id:
                order._update_analytics()
            
            return {
                'packed_quantity': detail.packed_quantity,
                'quantity': detail.quantity,
                'is_packed': detail.packed_quantity >= detail.quantity,
                'order_completed': all_packed
            }
        except Exception as e:
            logging.error(f'Ошибка в quick_pack_detail: {str(e)}')
            return {'error': str(e)}