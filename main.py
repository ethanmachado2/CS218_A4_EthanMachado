import datetime as dt
import uuid
import hashlib
import json
import os
import sys
import psycopg2
import time
from flask import Flask, jsonify, request, make_response, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import relationship
from sqlalchemy.exc import IntegrityError, OperationalError
from marshmallow import Schema, fields, validate, ValidationError

app = Flask(__name__)

# in-memory cache to speed up GET requests
# Key: order_id, Value: dictionary of order data
order_cache = {}

# function that returns the current date and time for timestamp purposes

def utcnow():
    return dt.datetime.now(dt.timezone.utc)

# function that generates a randomized id for requests

def new_id():
    return uuid.uuid4().hex

# function that assigns a randomized ID to requests

@app.before_request
def start_req():
    g.uniq_req_id = new_id()

# function to define structured logs

def struct_log(type, message, adt_data = None):
    log_dict = {
        "timestamp" : utcnow().isoformat(),
        "type" : type,
        "request_id" : getattr(g, 'uniq_req_id', 'N/A'),
        "message" : message
    }
    if adt_data:
        log_dict.update(adt_data)
    print(json.dumps(log_dict))

def canonical_json_bytes(payload: dict) -> bytes:
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

# database creation - old configuration using sqlite

# app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ordersmgmt.db"

# db = SQLAlchemy(app)

# database creation using Postgres

# DB_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/dbname")

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    # force system exit if DATABASE_URL env-driven variables are not set
    print(json.dumps({
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "type": "ERROR_LOG",
        "message": "CRITICAL: DATABASE_URL environment variable is not set. Service exiting."
    }))
    sys.exit(1)

app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

db = SQLAlchemy(app)

# db migrations provided

migrate = Migrate(app, db)

# orders database table model creation

class Orders(db.Model):
    __tablename__ = "orders"
    order_id  = db.Column(db.Integer, primary_key = True) #, default = new_id)
    status = db.Column(db.String, nullable = False, default = "created")
    customer_id = db.Column(db.String, nullable = False)
    item_id = db.Column(db.String, nullable = False)
    quantity = db.Column(db.Integer, nullable = False)
    created = db.Column(db.DateTime, nullable = False, default = utcnow)
    updated = db.Column(db.DateTime, nullable = False, default = utcnow, onupdate = utcnow)
    # notes = db.Column(db.String(255), nullable=True)
    ledger_entries = relationship("Ledger", back_populates="order", cascade="all, delete-orphan")

# function to return a record from the orders table as a dictionary for future use

    # def to_dict(self):
    #     return {
    #         "order_id" : self.order_id,
    #         "status" : self.status,
    #         "customer_id" : self.customer_id,
    #         "item_id" : self.item_id,
    #         "quantity" : self.quantity,
    #         "created" : self.created,
    #         "updated" : self.updated
    #     }

# ledger database table model creation that is related to the orders table

class Ledger(db.Model):
    __tablename__ = "ledger"
    __table_args__ = (
        UniqueConstraint("order_id", name = "unique_order_id"),
    )
    ledger_id  = db.Column(db.String, primary_key = True, default = new_id)
    order_id = db.Column(db.Integer, ForeignKey("orders.order_id"), nullable = False)
    created = db.Column(db.DateTime, nullable = False, default = utcnow)
    order = relationship("Orders", back_populates="ledger_entries")

# function to return a record from the ledger table as a dictionary for future use

    # def to_dict(self):
    #     return {
    #         "ledger_id" : self.ledger_id,
    #         "order_id" : self.order_id,
    #         "created" : self.created
    #     }

# idempotency_records database table model creation
    
class Idempotency(db.Model):
    __tablename__ = "idempotency_records"
    idem_key  = db.Column(db.String, primary_key = True)
    req_id = db.Column(db.String, nullable = False)
    req_status = db.Column(db.String, nullable = False, default = "in_process")
    req_hash = db.Column(db.String, nullable = False)
    req_response = db.Column(db.Text, nullable = True)
    req_code = db.Column(db.Integer, nullable = True)
    timestamp = db.Column(db.DateTime, nullable = False, default = utcnow)

# function to return a record from the idempotency_records table as a dictionary for future use

    # def to_dict(self):
    #     return {
    #         "idem_key" : self.idem_key,
    #         "req_id" : self.req_id
    #         "req_status" : self.req_status,
    #         "req_hash" : self.req_hash,
    #         "req_response" : self.req_response,
    #         "req_code" : self.req_code,
    #         "timestamp" : self.timestamp
    #     }

# need to create externalized Postgres DB

# with app.app_context():
#     db.create_all()

# updated ping with retries to check if db is available

with app.app_context():
    retries = 5
    while retries > 0:
        try:
            # simple select statement to check if db is available
            db.session.execute(text('SELECT 1'))
            struct_log("INFO_LOG", "Database connection verified.")
            break
        except Exception as e:
            # retry logic to check if db is available
            retries -= 1
            struct_log("WARNING_LOG", f"DB not ready, retrying... ({retries} left)", {"error": str(e)})
            time.sleep(2)
    if retries == 0:
        # failure condition if db is unavailable after retries
        struct_log("ERROR_LOG", "Could not connect to database after retries.")
        sys.exit(1)

# creation of a client request schema for request body validation

class OrderSchema(Schema):
    customer_id = fields.Str(required = True, validate = validate.Length(min = 1))
    item_id = fields.Str(required = True, validate = validate.Length(min = 1))
    quantity = fields.Int(required = True, validate = validate.Range(min = 1))

order_schema = OrderSchema()

# creation of Routes (API endpoints)
# "/" default route with information on other endpoints

@app.route("/")
def home():
    return jsonify({"message" : "/orders endpoint for order creation. /orders/<order_id> endpoint for order display."})

# main order processing endpoint that processes client order creation requests

@app.route("/orders", methods = ["POST"])
def orders_route():
    # generation of unique request ID
    # g.uniq_req_id = new_id()
    # getting the Idempotency-Key from the request header
    idempotency_key = request.headers.get("Idempotency-Key")
    # debug header created for testing commit without response failure scenario
    fail_after_commit = request.headers.get("X-Debug-Fail-After-Commit") == "true"
    struct_log("INFO_LOG", "Request received", {"path" : "/orders", "method" : "POST"})
    # check to determine if client requets contains an Idempotency-Key in its header
    if not idempotency_key:
         struct_log("WARNING_LOG", "Missing Idempotency-Key", {"status code" : 400})
         return make_response(jsonify({"Error" : "Missing Idempotency-Key"}), 400)
    # parsing of JSON request data
    json_req = request.get_json(silent = True)
    # checks for invalid client request based on request body data validation
    try:
        req_body = order_schema.load(json_req)
    except ValidationError as e:
        struct_log("WARNING_LOG", "Invalid request data", {"status code" : 422, "errors" : e.messages})
        return make_response(jsonify({"Error" : "Invalid data", "Messages" : e.messages}), 422)
    # returns HTTP 400 message if request body is not a valid python dictionary object
    if not isinstance(req_body, dict):
        struct_log("WARNING_LOG", "Invalid JSON body", {"status code" : 400})
        return make_response(jsonify({"Error" : "Invalid JSON body"}), 400)

    # creating a request body hash (fingerprint)
    req_hash = sha256_hex(canonical_json_bytes(req_body))

    # if the request is determined to be valid, then the order creation process begins
    try:
        # gets the first client request to avoid race conditions
        get_key = Idempotency.query.filter_by(idem_key = idempotency_key).first()

        # checks if Idempotency-Key value already exists in idempotency_records table
        if get_key:
            # if Idempotency-Key value already exists with different fingerprint, return 409 conflict
            if get_key.req_hash != req_hash:
                # db.session.rollback() -- rollback not needed here, done later on in process
                struct_log("WARNING_LOG", "Existing Idempotency-Key with different payload", {"status code" : 409})
                return make_response(jsonify({"Error" : "Existing Idempotency-Key with different payload"}), 409)
            # if Idempotency-Key value already exists with completed status, return original request response and status code
            if get_key.req_status == "completed":
                response = make_response(json.loads(get_key.req_response), get_key.req_code)
                response.headers["X-Request-ID"] = g.uniq_req_id
                struct_log("INFO_LOG", "Idempotency-Key and request fingerprint already exist", {"status code" : get_key.req_code})
                return response
            # if # if Idempotency-Key value already exists with in_process status, return 409 conflict
            if get_key.req_status == "in_process":
                # db.session.rollback() -- rollback not needed here, done later on in process
                struct_log("WARNING_LOG", "Existing request with same Idempotency-Key in process", {"status code" : 409})
                return make_response(jsonify({"Error" : "Request in process"}), 409)

        # if # if Idempotency-Key value does not exist, add Idempotency-Key record to idempotency_records table
        if not get_key:
            get_key = Idempotency(
                idem_key = idempotency_key,
                req_id = g.uniq_req_id,
                req_status = "in_process",
                req_hash = req_hash
                )
            db.session.add(get_key)
            # check if Idempotency-Key value is being handled by a different thread
            try:
                db.session.flush()
            except IntegrityError:
                db.session.rollback()
                struct_log("WARNING_LOG", "Same Idempotency-Key logged by a different thread", {"status code" : 409})
                return make_response(jsonify({"Error" : "Conflict: Idempotency-Key was just logged by another thread"}), 409)
    
        # creation of orders table entry
        order_creation = Orders(
            customer_id = req_body.get("customer_id"),
            item_id = req_body.get("item_id"),
            quantity = req_body.get("quantity")
        )
        db.session.add(order_creation)
        db.session.flush()

        # creation of ledger table entry associated with order
        ledger_entry = Ledger(
            order_id = order_creation.order_id,
        )
        db.session.add(ledger_entry)
    
        # generate response body for successful order creation
        response_body = {"order_id" : order_creation.order_id, "status" : "created"}

        # set response code to 201, set response body, and set status to completed in idempotency_records table
        get_key.req_code = 201
        get_key.req_response = json.dumps(response_body)
        get_key.req_status = "completed"

        struct_log("INFO_LOG", "Order created and to be committed", {"order_id" : order_creation.order_id})

        # commit idempotency_records, order, and ledger table entries at once
        db.session.commit()

        # pop cache entry if id exists in cache to prevent stale/incorrect reads
        order_cache.pop(order_creation.order_id, None)

        # exception raised if debug header is maintained in client request
        if fail_after_commit:
            struct_log("WARNING_LOG", "Simulated Failure: Data committed but no response sent", {"status code" : 500})
            raise Exception("Simulated Failure: Data committed but no response sent")

        # return 201 created status code with response body if order is created successfully
        end_response = make_response(jsonify(response_body), 201)
        end_response.headers["X-Request-ID"] = g.uniq_req_id
        struct_log("INFO_LOG", "Order created and committed", {"order_id" : order_creation.order_id, "status code" : 201})
        return end_response

    
    # exception raised with rollback in case of an error
    except Exception as e:
        db.session.rollback()
        struct_log("ERROR_LOG", "Internal Server Error", {"Error" : str(e), "status_code" : 500})
        error_response = make_response(jsonify({"Error" : str(e)}), 500)
        error_response.headers["X-Request-ID"] = g.uniq_req_id
        return error_response

# PUT order update endpoint to test in-memory cache correctness
# order that is updated is cleared from cache upon commit for correctness of future reads
@app.route("/orders/update/<int:id>", methods=["PUT"])
def update_order(id):
    struct_log("INFO_LOG", "Update request received", {"order_id" : id, "method" : "PUT"})
    
    # parsing of JSON request data
    json_req = request.get_json(silent=True)
    # checks for invalid client request based on request body data validation
    try:
        req_body = order_schema.load(json_req)
    except ValidationError as e:
        return make_response(jsonify({"Error" : "Invalid data", "Messages" : e.messages}), 422)

    try:
        # the existing order is retrieved and an error is returned if no order exists
        order = db.session.get(Orders, id)
        if not order:
            return make_response(jsonify({"Error" : "Order not found"}), 404)

        # customer_id, item_id, and quantity are all updated based on PUT request
        order.customer_id = req_body.get("customer_id")
        order.item_id = req_body.get("item_id")
        order.quantity = req_body.get("quantity")
        
        # order updates are committed to DB
        db.session.commit()

        # cached order is popped if maintained in cached for correctness of subsequent reads
        old_val = order_cache.pop(id, None)
        if old_val:
            struct_log("INFO_LOG", "Cache cleared for consistency", {"order_id" : id})

        # order status set to updated
        return jsonify({"order_id" : order.order_id, "status" : "updated"})

    # exceptions are caught and an error log is generated
    except Exception as e:
        db.session.rollback()
        struct_log("ERROR_LOG", "Update failed", {"Error": str(e)})
        return make_response(jsonify({"Error": str(e)}), 500)

# simple GET order endpoint that is searchable via {order_id}
# added in-memory caching functionality to return results more quickly for cached order_id records
# return 404 not found status code if {order_id} is not maintained in orders table
@app.route("/orders/<int:id>", methods = ["GET"])
def get_order(id):
    # check if id exists in cache and return cached result if yes
    if id in order_cache:
        struct_log("INFO_LOG", "Cache hit", {"order_id" : id})
        return jsonify(order_cache[id])
    # query DB if cache miss occurs and cache for future reads
    struct_log("INFO_LOG", "Cache miss - Querying DB", {"order_id" : id})
    order = db.session.get(Orders, id)
    # adding sleep duration to simulate DB query and network latency
    time.sleep(0.1)
    if order:
        order_data = {
            "order_id": order.order_id,
            "customer_id": order.customer_id,
            "item_id": order.item_id,
            "quantity": order.quantity            
        }
        order_cache[id] = order_data

        struct_log("INFO_LOG", "Order retrieved successfully and cached", {"order_id" : id})
        #return jsonify({"order_id" : order.order_id, "customer_id" : order.customer_id, "item_id" : order.item_id, "quantity" : order.quantity})
        return jsonify(order_data)
    struct_log("WARNING_LOG", "Order not found", {"status code" : 404})
    return (jsonify({"Error" : "Order not found"}), 404)


# simple GET health endpoint that checks the health of the backend Postgres db
@app.route("/health", methods = ["GET"])
def health():
    try:
        db.session.execute(text("SELECT 1"))
        struct_log("INFO_LOG", "Health check succeeded", {"status code" : 200})
        return (jsonify({"status:" : "ok", "db" : "connected"}), 200)
    except Exception as e:
        struct_log("ERROR_LOG", "Health check failed", {"error" : str(e)})
        return (jsonify({"status" : "error", "db" : "disconnected"}), 503)

if __name__ == "__main__":
    app.run(debug = True)