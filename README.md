# CS218_A4_EthanMachado
CS218 Assignment 4 Repository for Ethan Machado

Due date: 04/07/2026

Local setup steps and validation scenarios:

1. Use the following command to clone this respository: git clone https://github.com/ethanmachado2/CS218_A4_EthanMachado.git && cd CS218_A4_EthanMachado
2. Activate python virtual environment using the following command: source venv/bin/activate
3. Execute the following command to build and start the api and postgres containers: docker-compose up -d --build
4. Execute the following command to display all logs generated while the containers are running: docker-compose logs -f api
5. Create an order using the following curl command: curl -s -X POST http://localhost:8080/orders -H "Content-Type:application/json" -H "Idempotency-Key:test-999" -d '{"customer_id":"cust1","item_id":"item1","quantity":1}'
6. Retry with the same idempotency key using the following curl command: curl -s -X POST http://localhost:8080/orders -H "Content-Type:application/json" -H "Idempotency-Key:test-999" -d '{"customer_id":"cust1","item_id":"item1","quantity":1}'
7. Execute the following commands to check the database tables after creating the order: docker exec -it $(docker ps -qf "name=postgres") psql -U {DB_USER} -d {DB_NAME}
8. SELECT * FROM orders WHERE order_id = {order_id created in step #5};
9. SELECT * FROM ledger WHERE order_id = {order_id created in step #5};
10. SELECT * FROM idempotency_records WHERE idem_key = 'test-999';
11. Call the orders/{order_id} endpoint to read the order created in step #5. The first GET call should result in a DB query (cache miss). Check the logs to confirm.
12. Use the following command to confirm if the DB is queried upon the GET request (cache miss scenario): curl -i -w '\nTotal Time: %{time_total}s\n' http://localhost:8080/orders/{order_id created in step #5}
13. NOTE: A DELAY OF 0.1S WAS ADDED TO DB QUERIES TO SIMULATE THE NETWORK LATENCY PRESENT IN AN ACTUAL CLOUD DEPLOYMENT SCENARIO. THIS DELAY ILLUSTRATES THE BENEFITS OF CACHING.
14. Call the orders/{order_id} endpoint to read the order created in step #5. The second GET call should be served by the in-memory cache (cache hit). Check the logs to confirm.
15. Use the following command to confirm if the GET request is served by the in-memory cache (cache hit scenario): curl -i -w '\nTotal Time: %{time_total}s\n' http://localhost:8080/orders/{order_id created in step #5}
16. Update the order created in step #5 using the following command: curl -s -X PUT http://localhost:8080/orders/update/{order_id created in step #5} -H "Content-Type: application/json" -d '{"customer_id":"cust1","item_id":"item1","quantity":99}'
17. Call the orders/{order_id} endpoint to read the order updated in step #16. The first GET call should result in a DB query (cache miss), as the order has been cleared from cache. Check the logs to confirm.
18. Use the following command to confirm if the DB is queried upon the GET request (cache miss scenario) and to confirm if the order updates performed in step #16 are reflected: curl -i -w '\nTotal Time: %{time_total}s\n' http://localhost:8080/orders/{order_id created in step #5}
19. Execute the following commands to check the database tables after updating the order in step #16:
20. SELECT * FROM orders WHERE order_id = {order_id updated in step #16};
21. SELECT * FROM ledger WHERE order_id = {order_id updated in step #16};
22. SELECT * FROM idempotency_records WHERE idem_key = 'test-999';
