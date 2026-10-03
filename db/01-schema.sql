-- Schema for the booking application.
--
-- No schema file existed: the production database was created by hand on the
-- server, so this is reconstructed from every query in app.py. Column types fit
-- the values the application actually writes.
--
-- MySQL runs everything in /docker-entrypoint-initdb.d once, on first start of
-- an empty data volume. `docker compose down -v` resets it.

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- users
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    username   VARCHAR(150) NOT NULL,
    email      VARCHAR(255) NOT NULL,
    -- bcrypt hash from Flask-Bcrypt; 60 chars today, sized for future prefixes
    password   VARCHAR(255) NOT NULL,
    role       ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    is_active  TINYINT(1)   NOT NULL DEFAULT 1,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Login looks a user up by email, so it must be unique or the lookup is
    -- ambiguous. The original database did not enforce this.
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- resources -- the bookable rooms
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resources (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    capacity        INT NULL,
    -- Rendered into the booking summary as "€{cleaning_charge}".
    cleaning_charge DECIMAL(10,2) NULL DEFAULT 0.00,
    UNIQUE KEY uq_resources_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- inventory -- equipment available in a given room
--
-- Per-room equipment with a maximum quantity a booking may request. The public
-- form loads this over /get_inventory when a room is selected.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    resource_id  INT NOT NULL,
    name         VARCHAR(255) NOT NULL,
    max_quantity INT NOT NULL DEFAULT 1,
    -- Deleting a room removes its equipment rather than orphaning it. The
    -- original schema had no foreign key at all.
    CONSTRAINT fk_inventory_resource
        FOREIGN KEY (resource_id) REFERENCES resources (id) ON DELETE CASCADE,
    KEY idx_inventory_resource (resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- bookings
--
-- `resource` holds the room NAME rather than a foreign key, matching how the
-- application writes it (the form posts the selected name, and the overlap
-- check compares on it). Left as-is so the schema reflects the code;
-- normalising it is a worthwhile follow-up.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bookings (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    -- The public reference a customer uses to retrieve, modify or cancel.
    -- UNIQUE because it is a lookup key: the generator picks a random 6-digit
    -- number with no collision check, so the database has to be the backstop.
    booking_number    INT NOT NULL,

    first_name        VARCHAR(150) NULL,
    last_name         VARCHAR(150) NULL,
    academic_title    VARCHAR(100) NULL,
    organization      VARCHAR(255) NULL,
    email             VARCHAR(255) NULL,
    address           TEXT NULL,

    event_title       VARCHAR(255) NULL,
    start_date        DATE NULL,
    start_time        TIME NULL,
    end_date          DATE NULL,
    end_time          TIME NULL,
    resource          VARCHAR(255) NULL,
    participants      INT NULL,

    billing_info      TEXT NULL,
    cleaning_charge   VARCHAR(50) NULL,
    additional_info   TEXT NULL,
    contact_person    VARCHAR(255) NULL,
    inventory_items   TEXT NULL,
    services          TEXT NULL,

    -- Emailed to the customer to confirm a cancellation.
    cancellation_code VARCHAR(50) NULL,

    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_bookings_booking_number (booking_number),
    KEY idx_bookings_email (email),
    KEY idx_bookings_start_date (start_date),
    -- The double-booking check filters on resource + date range.
    KEY idx_bookings_resource_dates (resource, start_date, end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
