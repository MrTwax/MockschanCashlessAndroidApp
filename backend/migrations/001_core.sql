CREATE TABLE organizers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (btrim(name) <> '')
);

CREATE TABLE events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organizer_id uuid NOT NULL REFERENCES organizers(id),
    name text NOT NULL CHECK (btrim(name) <> ''),
    active boolean NOT NULL DEFAULT true,
    scan_timeout_seconds integer NOT NULL DEFAULT 120 CHECK (scan_timeout_seconds BETWEEN 30 AND 900),
    topup_amounts_cents integer[] NOT NULL DEFAULT '{500,1000,2000,5000}'
);

CREATE TABLE event_areas (
    event_id uuid NOT NULL REFERENCES events(id),
    area text NOT NULL CHECK (area IN ('cash', 'drinks', 'food', 'wine', 'mobile', 'admin')),
    enabled boolean NOT NULL,
    PRIMARY KEY (event_id, area)
);

CREATE TABLE devices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES events(id),
    name text NOT NULL CHECK (btrim(name) <> ''),
    key_hash bytea NOT NULL UNIQUE,
    revoked_at timestamptz,
    last_seen_at timestamptz,
    UNIQUE (event_id, id)
);

CREATE TABLE device_areas (
    event_id uuid NOT NULL,
    device_id uuid NOT NULL,
    area text NOT NULL,
    PRIMARY KEY (event_id, device_id, area),
    FOREIGN KEY (event_id, device_id) REFERENCES devices(event_id, id),
    FOREIGN KEY (event_id, area) REFERENCES event_areas(event_id, area)
);

CREATE TABLE pin_roles (
    event_id uuid NOT NULL,
    area text NOT NULL CHECK (area IN ('cash', 'admin')),
    pin_hash text NOT NULL,
    failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts BETWEEN 0 AND 5),
    blocked_until timestamptz,
    PRIMARY KEY (event_id, area),
    FOREIGN KEY (event_id, area) REFERENCES event_areas(event_id, area)
);

CREATE TABLE operator_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL,
    device_id uuid NOT NULL,
    area text NOT NULL,
    token_hash bytea NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    UNIQUE (event_id, device_id, area, id),
    FOREIGN KEY (event_id, device_id, area) REFERENCES device_areas(event_id, device_id, area)
);

CREATE TABLE accounts (
    event_id uuid NOT NULL REFERENCES events(id),
    uid text NOT NULL CHECK (uid ~ '^([0-9A-F]{2}){4,16}$'),
    balance_cents bigint NOT NULL DEFAULT 0 CHECK (balance_cents BETWEEN 0 AND 1000000000000),
    PRIMARY KEY (event_id, uid)
);

CREATE TABLE scans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL,
    device_id uuid NOT NULL,
    area text NOT NULL,
    uid text NOT NULL CHECK (uid ~ '^([0-9A-F]{2}){4,16}$'),
    expires_at timestamptz NOT NULL,
    closed_at timestamptz,
    UNIQUE (event_id, device_id, area, id),
    FOREIGN KEY (event_id, device_id, area) REFERENCES device_areas(event_id, device_id, area)
);

CREATE UNIQUE INDEX scans_one_open_per_area ON scans (event_id, device_id, area) WHERE closed_at IS NULL;

CREATE TABLE products (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL REFERENCES events(id),
    name text NOT NULL CHECK (btrim(name) <> ''),
    category text NOT NULL DEFAULT '',
    price_cents integer NOT NULL CHECK (price_cents BETWEEN 1 AND 100000000),
    areas text[] NOT NULL CHECK (cardinality(areas) > 0 AND areas <@ ARRAY['drinks', 'food', 'wine', 'mobile']),
    image_url text,
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    UNIQUE (event_id, id)
);

CREATE TABLE booking_requests (
    event_id uuid NOT NULL,
    device_id uuid NOT NULL,
    area text NOT NULL,
    request_id uuid NOT NULL,
    fingerprint bytea NOT NULL,
    status_code integer,
    response jsonb,
    PRIMARY KEY (event_id, device_id, request_id),
    UNIQUE (event_id, device_id, area, request_id),
    CHECK ((status_code IS NULL) = (response IS NULL)),
    FOREIGN KEY (event_id, device_id, area) REFERENCES device_areas(event_id, device_id, area)
);

CREATE TABLE transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL,
    device_id uuid NOT NULL,
    area text NOT NULL,
    request_id uuid NOT NULL,
    scan_id uuid NOT NULL UNIQUE,
    auth_session_id uuid NOT NULL,
    uid text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('topup', 'refund', 'sale')),
    payment_method text,
    amount_cents bigint NOT NULL CHECK (amount_cents > 0),
    balance_before_cents bigint NOT NULL CHECK (balance_before_cents BETWEEN 0 AND 1000000000000),
    balance_after_cents bigint NOT NULL CHECK (balance_after_cents BETWEEN 0 AND 1000000000000),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (event_id, id),
    CHECK ((kind = 'sale' AND area IN ('drinks', 'food', 'wine', 'mobile') AND payment_method IS NULL)
        OR (kind IN ('topup', 'refund') AND area = 'cash'
            AND payment_method IS NOT DISTINCT FROM 'cash')),
    CHECK (balance_after_cents = balance_before_cents
        + CASE WHEN kind = 'topup' THEN amount_cents ELSE -amount_cents END),
    FOREIGN KEY (event_id, device_id, area, request_id) REFERENCES booking_requests(event_id, device_id, area, request_id),
    FOREIGN KEY (event_id, device_id, area, scan_id) REFERENCES scans(event_id, device_id, area, id),
    FOREIGN KEY (event_id, device_id, area, auth_session_id) REFERENCES operator_sessions(event_id, device_id, area, id),
    FOREIGN KEY (event_id, uid) REFERENCES accounts(event_id, uid)
);

CREATE TABLE sale_items (
    event_id uuid NOT NULL,
    transaction_id uuid NOT NULL,
    product_id integer NOT NULL,
    product_name text NOT NULL,
    quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    unit_price_cents integer NOT NULL CHECK (unit_price_cents > 0),
    PRIMARY KEY (transaction_id, product_id),
    FOREIGN KEY (event_id, transaction_id) REFERENCES transactions(event_id, id),
    FOREIGN KEY (event_id, product_id) REFERENCES products(event_id, id)
);

CREATE INDEX transactions_event_time ON transactions (event_id, created_at, id);

CREATE FUNCTION refuse_journal_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'journal rows are append-only';
END;
$$;

CREATE TRIGGER transactions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON transactions
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_journal_change();
CREATE TRIGGER sale_items_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON sale_items
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_journal_change();
