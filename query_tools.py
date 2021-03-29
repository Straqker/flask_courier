from datetime import datetime
from collections import defaultdict


def data_to_db(db, table, time_table, data_json='', Regions='', capacity='', update=False):
    if data_json:
        keys = data_json[0].keys()
        id_key = [i for i in keys if 'id' in i][0]
        time_key = [i for i in keys if 'hours' in i][0]
        # Записываем по одному элементу (id)
        for item in data_json:
            try:
                if not update:
                    if id_key == 'courier_id':
                        item.update({'current_capacity': capacity.get(item['courier_type'])})
                    new_row = table(**item)
                    db.session.add(new_row)
                    db.session.flush()
                    db.session.commit()
                # Запишем регионы для каждого курьера в отдельную таблицу
                if id_key == 'courier_id':
                    regions = [{id_key: item[id_key], 'regions': region}
                               for region in item['regions']]
                    list_to_db(db, regions, Regions)
                # Аналогично для временных интервалов
                time_intervals = [{id_key: item[id_key], time_key: hours}
                                  for hours in item[time_key]]
                list_to_db(db, time_for_table(time_intervals, time_key), time_table)
            except:
                pass


def time_for_table(arr, time_key):
    # Запишем время начала и конца интервала
    for item in arr:
        time_interval = item[time_key].split('-')
        item.update({'start_time': datetime.strptime(time_interval[0], '%H:%M')})
        item.update({'end_time': datetime.strptime(time_interval[1], '%H:%M')})
        
    return arr


def list_to_db(db, data, table):
    for item in data:
        try:
            new_row = table(**item)
            db.session.add(new_row)
            db.session.flush()
            db.session.commit()
        except:
            pass


def match_orders(delivery_time, working_time, reverse=False):
    matching_orders = []
    for d in delivery_time:
        for w in working_time:
            if (d.start_time >= w.start_time) and (d.end_time <= w.end_time):
                matching_orders.append(d.order_id)
            elif (d.start_time <= w.start_time) and (d.end_time >= w.end_time):
                matching_orders.append(d.order_id)
    
    if reverse:
        return [d.order_id for d in delivery_time if d.order_id not in matching_orders]
    
    return matching_orders


def assign_orders(orders, courier_id, max_weight, courier_type, costs, reassign=False):
    # Сортируем список по возрастанию веса
    order_list = sorted([(order.order_id, order.weight)
                         for order in orders], key=lambda x: x[1])
    
    assign_time = datetime.now()
    to_assign = []
    idx_dict = []
    idx_list = []
    # Итерируемся по каждому заказу и вычитаем (при назначении) его массу из общей грузоподъемности
    for item in order_list:
        if item[1] <= max_weight:
            assign_dict = {'order_id': item[0],
                           'courier_id': courier_id,
                           'assign_time': assign_time,
                           'complete_time': datetime.strptime('00:00', '%H:%M'),
                           'delivery_cost': costs[courier_type]}
            to_assign.append(assign_dict)
            max_weight -= item[1]
            idx_dict.append({"id": item[0]})
            idx_list.append(item[0])
        else:
            break
    
    if reassign:
        return max_weight, idx_list
    
    if idx_dict:
        response = {"orders": idx_dict,
                    "assign_time": str(assign_time)}
    else:
        response = {"orders": idx_dict}
            
    return to_assign, max_weight, response


def drop_assign(db, courier_id, Courier, Order, Regions, Orders_assign, Delivery_hours, Working_hours, costs, change=False):
    # Переназначаем незавершенные заказы
    region = [item.regions for item in Regions.query.filter_by(courier_id=courier_id)]
    queued_orders = [item.order_id for item in Orders_assign.query.filter_by(courier_id=courier_id).all()]
    delivery_time = Delivery_hours.query.join(Order).filter(Order.region.in_(region),
                                                            Order.order_id.in_(queued_orders)).all()
    working_time = Working_hours.query.filter_by(courier_id=courier_id).all()
    # Получаем список заказов с подходящими временными интервалами
    matching_orders = match_orders(delivery_time, working_time)
    # Проверяем на возможный перегруз
    if change:
        courier = Courier.query.filter_by(courier_id=courier_id).all()
        courier_type, max_weight = courier[0].courier_type, courier[0].current_capacity
        new_capacity, matching_orders = assign_orders(Order.query.filter(Order.order_id.in_(matching_orders)),
                                                      courier_id, max_weight, courier_type, costs, True)
    orders_to_drop = list(set(queued_orders).difference(set(matching_orders)))
    # Удаляем заказы и списка назначенных, теперь они снова доступны для всех
    Orders_assign.query.filter(Orders_assign.order_id.in_(orders_to_drop),
                               Orders_assign.assign_time > Orders_assign.complete_time).delete(synchronize_session='fetch')
    # Возвращаем вес отмененных заказов
    if change:
        Courier.query.filter_by(courier_id=courier_id).update({'current_capacity': new_capacity})
    else:
        drop_weight(db, courier_id, orders_to_drop, Courier, Order)
    db.session.commit()


def drop_weight(db, courier_id, orders_id, Courier, Order):
    # Возвращаем в "текущую грузоподъемность" отмененные заказы
    orders_weight = [item.weight for item in Order.query.filter(Order.order_id.in_(orders_id)).all()]
    current_weight = Courier.query.filter_by(courier_id=courier_id).all()[0].current_capacity
    Courier.query.filter_by(courier_id=courier_id).update({'current_capacity': current_weight + sum(orders_weight)})
    db.session.commit()


def get_rating(completed_orders, orders, courier_id, Courier):
        # Считаем время доставки для каждого заказа
        delivery_time = {}
        order = completed_orders[0]
        delivery_time[order.order_id] = (order.complete_time - order.assign_time).seconds
        previos_completed_time = order.complete_time
        for order in completed_orders[1:]:
            delivery_time[order.order_id] = (order.complete_time - previos_completed_time).seconds
            previos_completed_time = order.complete_time
        # Для каждого региона формируем свой списко с временем доставки
        region_avg_del_time = defaultdict(list)
        for item in orders:
            region_avg_del_time[item.region].append(delivery_time[item.order_id])
        # Находим минимальное среднее время доставки
        boo = []
        for key in region_avg_del_time.keys():
            dev_time = region_avg_del_time[key]
            boo.append(sum(dev_time)/len(dev_time))
        min_dev_time = min(boo)
        # Считаем рейтинг и заработок
        rating =  round((60*60 - min(min_dev_time, 60*60))/(60*60) * 5, 2)
        earning = sum([item.delivery_cost for item in completed_orders])
        
        res = Courier.query.filter_by(courier_id=courier_id)[0]
        response = {"courier_id": res.courier_id,
                    "courier_type": res.courier_type,
                    "regions": res.regions,
                    "working_hours": res.working_hours,
                    "rating": rating,
                    "earnings": earning}
        
        return response
