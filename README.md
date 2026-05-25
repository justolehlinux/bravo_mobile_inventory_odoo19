# Bravo Mobile Inventory — Odoo 19

Мобильный терминал физической инвентаризации для Bravo Market.

## Что делает MVP

- открывает страницу `/mobile/inventory` без стандартной складской формы;
- создаёт отдельную сессию подсчёта;
- считает **одну точную внутреннюю локацию** за сессию;
- сканирует основной `product.product.barcode`;
- позволяет уполномоченному пользователю привязать неизвестный штрихкод к существующему товару без штрихкода;
- хранит counted quantity до финального подтверждения;
- показывает review и dry-run;
- применяет `stock.quant.inventory_quantity` только менеджером склада и только без конфликтов.

## Ограничения первой версии

- товары с lot/serial tracking блокируются;
- quants с `lot_id`, `package_id` или `owner_id` блокируются;
- один товар — один основной штрихкод; замена существующего штрихкода через мобильную страницу запрещена;
- привязка barcode сохраняется сразу и не откатывается при отмене сессии;
- выбранная локация считается строго (`strict=True`), дочерние локации не входят в количество.

## Установка

1. Скопируйте папку `bravo_mobile_inventory` в custom addons Odoo.
2. Перезапустите Odoo.
3. Обновите список приложений.
4. Установите **Bravo Mobile Inventory**.
5. Назначьте пользователям группу склада и, при необходимости, группу **Bind Product Barcodes from Mobile Inventory**.
6. Применение остатков доступно только пользователям группы `Inventory / Administrator` (`stock.group_stock_manager`).

## Обязательная проверка перед production

1. Установить модуль на тестовой базе-копии.
2. Выбрать точную внутреннюю локацию с 2–3 обычными товарами без партий.
3. Проверить сканирование, привязку barcode и review.
4. Выполнить preview и apply.
5. Проверить в Odoo историю inventory moves и итоговые quants.
6. Только после этого давать доступ реальному складу.

## API маршруты

- `POST /mobile/inventory/start`
- `POST /mobile/inventory/scan`
- `POST /mobile/inventory/search_product`
- `POST /mobile/inventory/bind_barcode`
- `POST /mobile/inventory/set_qty`
- `POST /mobile/inventory/skip`
- `POST /mobile/inventory/finish`
- `POST /mobile/inventory/reopen`
- `POST /mobile/inventory/review`
- `POST /mobile/inventory/preview_apply`
- `POST /mobile/inventory/apply`
- `POST /mobile/inventory/cancel`
