import jsonschema
import yaml


class Validator:
    def __init__(self, openapi_path, url, method):
        with open(openapi_path) as file:
            self._openapi = yaml.load(file, Loader=yaml.FullLoader)
        self._url = str(url)
        self._method = method.lower()
        self._type = {'/couriers': ['courier_id', 'couriers'],
                      '/orders': ['order_id', 'orders']}
        self._validator_init()
        
    def _validator_init(self):
        # инициализируем resolver и schemastore из файла openapi.yaml
        self._schemastore = {f'/components/schemas/{key}': self._openapi['components']['schemas'][key]
                             for key in self._openapi['components']['schemas'].keys()}
        self._resolver = jsonschema.RefResolver(base_uri='/components/schemas/',
                                                referrer=self._openapi,
                                                store=self._schemastore)
        # инициализируем validator и получаем schema для проверяемого объекта
        self._schema = self._openapi['paths'][self._url][self._method]['requestBody']['content']['application/json']['schema']
        self._validator = jsonschema.Draft7Validator(self._schema, resolver=self._resolver)
    
    def update_validate(self, data_json):
        if self._validator.is_valid(data_json):
            return (data_json, 200)
        else:
            return ('', 400)
    
    def validate(self, data_json):
        # Если нет проблем, то возвращаем весь входной JSON и получаем id для ответа сервера
        if self._validator.is_valid(data_json):
            valid_response = {f'{self._type[self._url][1]}': ''}
            list_of_idx = [{'id': item[self._type[self._url][0]]} for item in data_json['data']]
            valid_response[f'{self._type[self._url][1]}'] = list_of_idx
            return (data_json, valid_response, 201)
        # Если есть проблемы, то возвращаем только валидный входной JSON и получаем id для ответа сервера
        else:
            errors = self._validator.iter_errors(data_json)
            error_idx = [list(error.path)[1] for error in errors]
            response = self._valid_error_response(data_json, error_idx)
            
            return (*response, 400)

    def _valid_error_response(self, data_json, error_idx):
            valid_response = {'validation_error': {}}
            list_of_idx = [{'id': data_json['data'][i].get(self._type[self._url][0])} for i in error_idx]
            valid_response['validation_error'].update({f'{self._type[self._url][1]}': list_of_idx})
            
            new_data = {'data': [item for i, item in enumerate(data_json['data']) if i not in error_idx]}

            return (new_data, valid_response)
