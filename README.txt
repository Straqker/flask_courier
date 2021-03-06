Приветствую!
Здесь будет краткая инструкция по установке и развертыванию web сервиса по доставке.

1. Скачать (клонировать) сервис с репозитория на GitHub в любой удобный каталог на машине.
2. Данный репозиторий будет работать используя Docker (убедиться, что Docker установлен).
Все необходимые параметры описаны в Dockerfile в корне репозитория.
(В принципе можно обойтись без Docker, тогда для запуска будет нужно запустить файл "app.py").
3. В корне репозитория есть файл "requirements.txt", и при создании Docker image автоматически 
будут установлены все необходимые зависимости.
4. Перейти в корневую папку с репозиторием. Создать образ Docker image: 
"sudo docker build -t NAME ."
5. Валидатор в приложении использует данные из файла "openapi.yaml" (папка /data), 
если будет необходимость несколько изменить способы валидации (например добавить новую категорию в "courier_type"), 
его можно будет примонтировать (собственно также как и базу данных), чтобы или вносить в них изменения 
при работающем контейнере (а также сохранять изменения при остановке или перезагрузке).
Для этого запустить команду (в -p 8080:8080 выбрать желаемый порт):
"sudo docker run -p 8080:8080 -e TZ=Europe/Moscow --restart always -v your_absolute_path/data:/usr/src/app/data NAME"
 (--restart always  -  контейнер будет сам автоматически запускаться после перезагрузки сервера).
 6. Все, веб-приложение успешно запущено и работает. 
 Для проверки его работоспособности в корне лежит jupyter notebook "test_app.ipynb".


==================
Функционал
==================

В данном приложении реализованы все 6 методов.
Более подробное описание их можно найти в __doc__ самих функций в файле ("app.py").

В приложении есть валидатор ("valid.py"), он использует информацию для валидации 
из файла "openapi.yaml" (папка /data). Если при запуске контейнера была примонтирована 
папка с этим файлом (как в инструкции), то условия валидации можно менять даже у запущенного веб-приложения.

Также для работы приложение использует базу данных SQLite (data/test.db, если нет, 
то при запуске сервера создается автоматически).
И 6 таблиц (команду для их создания можно найти в app.py):
1) Courier - содержит информацию о курьере (без изменения, передаваемую при инициализации), 
а также информацию о текущей загруженности курьера (текущей грузоподъемности).
2) Regions - содержит информацию о регионах, где работает курьер (для каждого региона своя строка).
3) Working_hours - аналогично "Regions", только здесь содержатся интервалы времени работы курьера в двух столбцах - 
start_time (время начала) и end_time (время конца).
4) Order - содержит информацию о всех заказах.
5) Delivery_hours - аналогично "Working_hours", но только для заказов.
6) Orders_assign - таблица содержит информацию о назначенных заказах. 
assign_time - время назначения, complete_time - время доставки, delivery_cost - стоимость доставки 
(высчитывается во время назначения в зависимости от типа курьера).
