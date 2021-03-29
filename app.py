from datetime import datetime
from collections import defaultdict
from flask import Flask, request, jsonify, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
import sqlite3
import yaml

from valid import Validator
from query_tools import data_to_db, time_for_table, list_to_db, match_orders, assign_orders, drop_assign, drop_weight, get_rating

PATH_OPENAPI = 'data/openapi.yaml'
SQLALCHEMY_DATABASE_URI = 'sqlite:///data/test.db'
capacity = {'foot': 10, 
            'bike': 15,
            'car': 50}
costs = {'foot': 2*500,
         'bike': 5*500,
         'car': 9*500}

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    courier_id = db.Column(db.Integer, unique=True, nullable=False)
    courier_type = db.Column(db.String(50), nullable=False)
    regions = db.Column(db.PickleType, nullable=False)
    working_hours = db.Column(db.PickleType, nullable=False)
    current_capacity = db.Column(db.Integer, nullable=False)


class Regions(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    courier_id = db.Column(db.Integer, db.ForeignKey('courier.courier_id'), nullable=False)
    regions = db.Column(db.Integer, nullable=False)

 
class Working_hours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    courier_id = db.Column(db.Integer, db.ForeignKey('courier.courier_id'), nullable=False)
    working_hours = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, unique=True, nullable=False)
    weight = db.Column(db.Float, nullable=False)
    region = db.Column(db.Integer, nullable=False)
    delivery_hours = db.Column(db.PickleType, nullable=False)


class Delivery_hours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.order_id'), nullable=False)
    delivery_hours = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)


class Orders_assign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.order_id'), unique=True, nullable=False)
    courier_id = db.Column(db.Integer, db.ForeignKey('courier.courier_id'), nullable=False)
    assign_time = db.Column(db.DateTime, nullable=False)
    complete_time = db.Column(db.DateTime, nullable=True)
    delivery_cost = db.Column(db.Integer, nullable=True)


@app.route('/couriers', methods=['POST'])
def get_couriers():
    """
    Функция получает список курьеров.
    После валидации возвращает либо номера курьеров (если все валидные), либо номера невалидных 
    (валидные при это все равно записываются в базу данных).
    """
    validator = Validator(PATH_OPENAPI, url_for('get_couriers'), 'POST')
    response = validator.validate(request.json)
    data_to_db(db, Courier, Working_hours, response[0]['data'], Regions, capacity)
    
    return make_response(jsonify(response[1]), response[2])


@app.route('/orders', methods=['POST'])
def get_orders():
    """
    Функция получает список заказов.
    После валидации возвращает либо номера заказов (если все валидные), либо номера невалидных 
    (валидные при это все равно записываются в базу данных).
    """
    validator = Validator(PATH_OPENAPI, url_for('get_orders'), 'POST')
    response = validator.validate(request.json)
    data_to_db(db, Order, Delivery_hours, response[0]['data'])
    
    return make_response(jsonify(response[1]), response[2])


@app.route('/couriers/<int:courier_id>', methods=['POST'])
def update_courier(courier_id):
    """
    Функция изменения информации о курьере.
    После внесения изменений проверяет все уже присвоенные заказы на актуальность и снимает те, 
    которые уже не подходят (другой регион, время доставки или перегруз).
    Возвращет JSON c актуальной информацией о курьере.
    """
    # Валидация записи
    validator = Validator(PATH_OPENAPI, '/couriers/{courier_id}', 'patch')
    response = validator.update_validate(request.json)
    if not response[0]:
        return make_response(jsonify(response[0]), response[1])
    # Удаляем записи из Regions и Working_hours
    Regions.query.filter_by(courier_id=courier_id).delete()
    Working_hours.query.filter_by(courier_id=courier_id).delete()
    
    change = False
    if response[0].get('courier_type'):
        change = True
        response[0].update({'current_capacity': capacity.get(response[0]['courier_type'])})
    Courier.query.filter_by(courier_id=courier_id).update(response[0])
    db.session.commit()
    # Получаем модифицированную запись и создаем новые записи в вспомогательных таблицах (Regions, Working_hours)
    res = Courier.query.filter_by(courier_id=courier_id)[0]
    answer = {"courier_id": res.courier_id,
              "courier_type": res.courier_type,
              "regions": res.regions,
              "working_hours": res.working_hours}
    data_to_db(db, Courier, Working_hours, [answer], Regions, update=True)
    
    # Отменяем неподходящие (но ранее назначенные) заказы
    drop_assign(db, courier_id, Courier, Order, Regions, Orders_assign,
                Delivery_hours, Working_hours, costs, change)
    
    return make_response(jsonify(answer), response[1])


@app.route('/orders/assign', methods=['POST'])
def orders_assign():
    """
    Функция присваивания заказа курьеру.
    Уменьшает грузоподъемность курьера на массу назначенных заказов.
    Назначает заказ только если интервалы времени доставки и времени работы курьера вложены 
    (либо время доставки содержится в любом интервале времени работы, либо время работы в интервале доставки).
    В случае прохождения валидации, возвращает JSON с номерами назначенных заказов и временем назначения.
    """
    # Валидация записи
    validator = Validator(PATH_OPENAPI, url_for('orders_assign'), 'POST')
    response = validator.update_validate(request.json)
    number = response[0]['courier_id']
    if len(Courier.query.filter_by(courier_id=number).all()) == 0:
        return make_response(jsonify({}), 400)
    
    # Получаем список времени доставки по заказам, с подходящими регионами доставки
    regions = [item.regions for item in Regions.query.filter_by(courier_id=number).all()]
    queued_orders = [item.order_id for item in Orders_assign.query.all()]
    delivery_time = Delivery_hours.query.join(Order).filter(Order.region.in_(regions),
                                                            Order.order_id.notin_(queued_orders)).all()
    working_time = Working_hours.query.filter_by(courier_id=number).all()
    # Получаем список заказов с подходящими временными интервалами
    matching_orders = match_orders(delivery_time, working_time)
    # Подходящий список заказов (order_id)
    orders = Order.query.filter(Order.order_id.in_(matching_orders)).all()
    courier = Courier.query.filter_by(courier_id=number).all()
    courier_type, max_weight = courier[0].courier_type, courier[0].current_capacity
    # Получаем подходищие заказы и оставшуюся грузоподъемность
    orders_to_assign, new_capacity, response = assign_orders(orders, number, max_weight, courier_type, costs)
    # Обновляем оставшуюся грузоподъемность
    Courier.query.filter_by(courier_id=number).update({'current_capacity': new_capacity})
    db.session.commit()
    
    list_to_db(db, orders_to_assign, Orders_assign)

    return make_response(jsonify(response), 200)


@app.route('/orders/complete', methods=['POST'])
def complete_order():
    """
    Функция завершения доставки.
    Также восстанавливает грузоподъемность курьера на массу доставленного заказа.
    В случае прохождения валидации (заказ существует и приписан правильному курьеру),
    возвращает JSON с номером завершенного заказа.
    """
    # Валидация записи
    validator = Validator(PATH_OPENAPI, url_for('complete_order'), 'POST')
    response = validator.update_validate(request.json)
    courier, order, finish_time = response[0]['courier_id'], response[0]['order_id'], response[0]['complete_time']
    finish_time = datetime.fromisoformat(finish_time)
    
    completed_ = Orders_assign.query.filter(Orders_assign.courier_id==courier,
                                            Orders_assign.order_id==order,
                                            Orders_assign.assign_time > Orders_assign.complete_time).all()
    if len(completed_) == 0:
        return make_response(jsonify({}), 400)
    else:
        Orders_assign.query.filter_by(courier_id=courier, order_id=order).update({'complete_time': finish_time})
        db.session.commit()
        drop_weight(db, courier, [order], Courier, Order)

    return make_response(jsonify({"order_id": order}), 200)


@app.route('/couriers/<int:courier_id>', methods=['GET'])
def get_courier_stats(courier_id):
    """
    Функция считает рейтинг и суммарный заработок курьера.
    Возвращает JSON с основной информацией о курьере + рейтинг и суммарный заработок.
    """
    # Получаем список выполненных курьером заказов
    completed_orders = Orders_assign.query.filter(Orders_assign.courier_id==courier_id,
                                                  Orders_assign.assign_time < Orders_assign.complete_time).order_by(Orders_assign.complete_time).all()
    
    if len(completed_orders) == 0:
        return make_response(jsonify({}), 400)
    # Список всех order_id
    orders_id = [item.order_id for item in completed_orders]
    orders = Order.query.filter(Order.order_id.in_(orders_id)).all()
    
    response = get_rating(completed_orders, orders, courier_id, Courier)

    return jsonify(response)


if __name__ == "__main__":
    db.create_all()
    app.run(host="0.0.0.0", port="8080")
