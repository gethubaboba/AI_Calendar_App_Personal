Приоритет 0 — пользовательские сценарии календаря
1. После создания события пропадает кнопка создания события. На правой панели кнопка + Создать событие находится только внутри ветки, которая показывается, когда в выбранном дне нет ни событий, ни заметок. Как только появляется первая запись, панель переключается на список и эта кнопка исчезает. В пустом состоянии также показывается только «Нет событий», даже если есть заметки.
   Файл: [dashboard/page.tsx (line 298)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:298).
   Приёмка: кнопка создания события остаётся доступна при любом количестве событий и заметок; панель корректно показывает состояние, когда в дне есть только заметки.
2. Нельзя открыть отдельный вид выбранного дня. Сейчас доступны только месячный и недельный режимы. Выбор даты в календаре обновляет правую панель, но отдельного дневного календарного вида нет.
   Файлы: [dashboard/page.tsx (line 216)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:216), [index.ts (line 40)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/types/index.ts:40).
   Приёмка: пользователь может открыть день из месячного и недельного вида, просмотреть записи выбранной даты и создать оттуда событие или заметку.
3. Созданная из календаря заметка не появляется сразу. handleSaveNote отправляет запрос, но не добавляет ответ API в локальное состояние notes и не перезагружает данные.
   Файл: [dashboard/page.tsx (line 154)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:154).
   Приёмка: после успешного сохранения заметка немедленно появляется в списке выбранного дня и, если у неё есть дата, в календаре.
4. Форма события закрывается, даже если API вернул ошибку. В handleSave ошибка показывается через alert, но после catch выполнение доходит до setShowForm(false).
   Файл: [dashboard/page.tsx (line 118)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:118).
   Приёмка: при ошибке форма остаётся открытой, введённые значения сохранены, пользователь видит сообщение; при успехе форма закрывается.
5. Ошибки загрузки календаря не сообщаются пользователю. loadEvents сбрасывает loading в finally, но не обрабатывает исключение. В результате ошибка API может выглядеть как пустой календарь.
   Файл: [dashboard/page.tsx (line 55)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:55).
   Приёмка: ошибка загрузки показывается отдельно от состояния «нет событий» и даёт возможность повторить загрузку.
6. Удаление событий и заметок не требует подтверждения. Обработчики сразу вызывают DELETE; восстановления или отмены в интерфейсе нет.
   Файлы: [dashboard/page.tsx (line 138)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:138), [notes/page.tsx (line 70)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/notes/page.tsx:70).
   Приёмка: перед удалением есть понятное подтверждение; при отмене данные остаются на месте.
7. Действия с заметками скрыты на сенсорных устройствах. Кнопки редактирования и удаления используют opacity-0 group-hover:opacity-100, поэтому без hover они могут быть не видны.
   Файл: [notes/page.tsx (line 125)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/notes/page.tsx:125).
   Приёмка: действия с заметкой доступны на touch-экранах и клавиатурой, не только при наведении мыши.
Приоритет 0 — backend, API и целостность данных
8. Backend принимает некорректные события. В схемах type — произвольная строка; нет проверки, что end_time позже start_time, и что интервал либо задан целиком, либо отсутствует. Для обновления события эти проверки тоже необходимы с учётом уже сохранённых значений.
   Файлы: [schemas.py (line 66)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/schemas.py:66), [events.py (line 77)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/routers/events.py:77).
   Приёмка: API отклоняет неизвестный тип, неполный временной интервал и окончание раньше начала с понятным 4xx; корректные данные проходят. Frontend показывает соответствующие ошибки до отправки.
9. Событие может ссылаться на чужой шаблон. EventCreate принимает template_id, а создание события передаёт данные напрямую в модель, не проверяя владельца шаблона. Frontend при этом не предоставляет рабочего использования шаблонов.
   Файлы: [schemas.py (line 66)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/schemas.py:66), [events.py (line 53)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/routers/events.py:53), [templates.py (line 23)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/routers/templates.py:23).
   Приёмка: API разрешает применить только шаблон текущего пользователя; чужой или несуществующий ID не создаёт событие. Если шаблоны входят в MVP, интерфейс позволяет создать, выбрать и удалить свой шаблон.
10. Уведомления не доведены до работающей функции. Backend предоставляет получение и отметку прочитанными, но в проекте не найдено создание уведомлений или механизм доставки. На Dashboard список уведомлений постоянно инициализирован пустым массивом; другие страницы также передают пустые массивы, обработчики отметки прочитанным отсутствуют.
    Файлы: [dashboard/page.tsx (line 33)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/dashboard/page.tsx:33), [Header.tsx (line 18)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/components/Header.tsx:18), [notifications.py (line 22)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/routers/notifications.py:22).
    Приёмка: если уведомления остаются в MVP, определены и реализованы их создание, отображение и отметка прочитанными. Если не остаются — функция убрана из интерфейса и заявлений о готовых возможностях.
11. Количество заметок в аналитике считается по событиям, а не по записям раздела заметок. Backend возвращает total_notes, но карточка на странице получает число из событий типа note, поэтому оно может не совпадать с количеством настоящих заметок.
    Файлы: [analytics.py (line 30)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/routers/analytics.py:30), [analytics/page.tsx (line 121)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/analytics/page.tsx:121).
    Приёмка: интерфейс использует total_notes для количества заметок; число событий типа note отображается отдельно либо не называется количеством заметок.
12. Миграции БД не соответствуют инструкции запуска. При старте приложение выполняет Base.metadata.create_all(), а backend/alembic/versions содержит только .keep. README предлагает alembic upgrade head, но начальной миграции нет. Это оставляет новые установки и обновления схемы без единого управляемого пути.
    Файлы: [main.py (line 21)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/main.py:21), [alembic/versions](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/alembic/versions), [README.md](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/README.md).
    Приёмка: добавлена начальная миграция; новая БД поднимается через Alembic; дальнейшие изменения схемы тоже выполняются миграциями; автосоздание таблиц при старте приложения удалено или явно обосновано.
13. OAuth заявлен, но не реализован. В документации перечислены вход через Google и Microsoft, а backend содержит маршруты email-регистрации, входа, refresh и профиля; OAuth-маршрутов и реализации провайдеров не найдено.
    Файлы: [auth.py (line 25)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/routers/auth.py:25), [README.md](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/README.md).
    Приёмка: либо OAuth реализован и проходит сценарий входа, либо удалён из описания текущих возможностей и требований MVP.
Приоритет 1 — даты, время и настройки окружения
14. Преобразование календарных дат через UTC может сдвигать день. Даты вроде YYYY-MM-DD формируются вызовами toISOString().slice(0, 10) после работы с локальным временем. Это используется в календаре и аналитике, а также для «сегодня» и начальной даты формы.
    Файлы: [MonthView.tsx (line 30)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/components/Calendar/MonthView.tsx:30), [WeekView.tsx (line 38)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/components/Calendar/WeekView.tsx:38), [analytics/page.tsx (line 54)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/app/analytics/page.tsx:54), [EventForm.tsx (line 22)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/components/EventForm.tsx:22).
    Приёмка: календарная дата обрабатывается как дата без времени; проверки для разных часовых поясов показывают один и тот же выбранный пользователем день.
15. CORS разрешает любые источники. Это может быть приемлемо для локального прототипа, но не подходит как конфигурация публичного окружения.
    Файл: [main.py (line 39)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/main.py:39).
    Приёмка: разрешённые origins задаются конфигурацией окружения; в инструкции описано значение для локального запуска.
16. AI-интерфейс и backend называют разные модели. Сервис использует локальный Ollama с qwen2.5:1.5b, но виджет, согласно приложенному списку, сообщает про DeepSeek. backend/test_ai.py проверяет старую интеграцию DeepSeek и не соответствует текущему сервису. Это отдельная от ядра календаря задача.
    Файлы: [ai_service.py (line 9)](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/services/ai_service.py:9), [AIWidget.tsx](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/frontend/src/components/AIWidget.tsx), [test_ai.py](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/backend/test_ai.py).
    Приёмка: подпись интерфейса соответствует реально используемой модели и конфигурации; устаревшая проверка DeepSeek удалена или заменена проверкой текущего сервиса.
17. Документация содержит неподтверждённые сценарии запуска. README описывает .env.example и миграции Alembic, однако среди перечисленных файлов backend нет .env.example, а каталог миграций пуст. Docker Compose требует backend/.env, а frontend запускается отдельно.
    Файлы: [README.md](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/README.md), [docker-compose.yml](/C:/BSU/lababot/students/shibitov/Kursovoi_Project/docker-compose.yml).
    Приёмка: инструкции проверены на чистом окружении и описывают реально существующие файлы и команды, включая запуск frontend, API и БД.
Рекомендуемый порядок для агента
1. Сначала согласовать состав MVP и контракт API, включая решение по OAuth, уведомлениям и шаблонам.
2. Исправить календарный сценарий и синхронизацию интерфейса: кнопка события, дневной вид, обновление заметок, обработка ошибок.
3. Исправить валидацию и проверку владения данными на backend.
4. Привести схему БД, миграции, CORS и инструкции запуска к единому рабочему процессу.
5. Исправить аналитику и отображение дат, затем сверить документацию и подписи AI.
6. В конце проверить руками основной сценарий: регистрация → вход → выбор дня → создание, изменение и удаление записей → переход в аналитику → повторный вход и проверка сохранности данных.