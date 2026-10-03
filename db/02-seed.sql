-- Demo data. Entirely fictional -- invented people at .example addresses,
-- generic room names. Runs once after 01-schema.sql on an empty data volume.

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- Accounts. Both hashes are bcrypt of the password in the comment; they are
-- demo credentials for a local stack, published deliberately so a fresh clone
-- can log in. Change them before exposing this anywhere.
-- --------------------------------------------------------------------------
INSERT INTO users (username, email, password, role, is_active) VALUES
  -- admin@example.com / admin123
  ('admin', 'admin@example.com', '$2b$12$vZawVFWGO7RK02eTWOC3dOganWVyZzHyGVUGraoPjpCDgHLVRwJmG', 'admin', 1),
  -- user@example.com / user123
  ('demo_user', 'user@example.com', '$2b$12$04LDSmftwLux7QRT2wKod.vOQIIx/BSERcOdIeIu0wW01YJByG68.', 'user', 1);

-- --------------------------------------------------------------------------
-- Bookable rooms
-- --------------------------------------------------------------------------
INSERT INTO resources (name, capacity, cleaning_charge) VALUES
  ('Main Hall',      120,  85.00),
  ('Seminar Room A',  40,  45.00),
  ('Seminar Room B',  20,  35.00),
  ('Meeting Room',    12,  20.00);

-- --------------------------------------------------------------------------
-- Per-room equipment, with the maximum a booking may request
-- --------------------------------------------------------------------------
INSERT INTO inventory (resource_id, name, max_quantity) VALUES
  ((SELECT id FROM resources WHERE name = 'Main Hall'),      'Projector',       2),
  ((SELECT id FROM resources WHERE name = 'Main Hall'),      'Microphones',     8),
  ((SELECT id FROM resources WHERE name = 'Main Hall'),      'Stage Lighting',  1),
  ((SELECT id FROM resources WHERE name = 'Seminar Room A'), 'Projector',       1),
  ((SELECT id FROM resources WHERE name = 'Seminar Room A'), 'Flipcharts',      4),
  ((SELECT id FROM resources WHERE name = 'Seminar Room A'), 'Moderation Kit',  2),
  ((SELECT id FROM resources WHERE name = 'Seminar Room B'), 'Flipcharts',      2),
  ((SELECT id FROM resources WHERE name = 'Seminar Room B'), 'Whiteboard',      1),
  ((SELECT id FROM resources WHERE name = 'Meeting Room'),   'Whiteboard',      1),
  ((SELECT id FROM resources WHERE name = 'Meeting Room'),   'Conference Phone',1);

-- --------------------------------------------------------------------------
-- Bookings -- a mix of past and upcoming so the calendar and the dashboard
-- counters both have something to show.
-- --------------------------------------------------------------------------
INSERT INTO bookings
  (booking_number, first_name, last_name, academic_title, organization, email,
   address, event_title, start_date, start_time, end_date, end_time, resource,
   participants, billing_info, cleaning_charge, additional_info, contact_person,
   inventory_items, services)
VALUES
  (204817, 'Jane', 'Miller', 'Dr.', 'Acme GmbH', 'jane.miller@example.com',
   'Alexanderplatz 10, 10178 Berlin', 'Quarterly Strategy Workshop',
   CURRENT_DATE + INTERVAL 3 DAY, '09:00:00', CURRENT_DATE + INTERVAL 3 DAY, '17:00:00',
   'Seminar Room A', 24, 'Invoice to accounts payable', '45.00',
   'Requires step-free access.', 'Jane Miller', 'Projector (1), Flipcharts (2)', 'Technician'),

  (551093, 'Marco', 'Rossi', '', 'Northwind Labs', 'marco.rossi@example.com',
   'Schwedter Str. 22, 10435 Berlin', 'Product Design Review',
   CURRENT_DATE + INTERVAL 7 DAY, '13:30:00', CURRENT_DATE + INTERVAL 7 DAY, '16:00:00',
   'Meeting Room', 8, 'Prepaid', '20.00', '', 'Marco Rossi', 'Whiteboard (1)', ''),

  (738264, 'Amina', 'Okonkwo', 'Prof.', 'Riverside Institute', 'amina.okonkwo@example.com',
   'Karl-Marx-Allee 90, 10243 Berlin', 'Public Lecture: Open Data',
   CURRENT_DATE + INTERVAL 14 DAY, '18:00:00', CURRENT_DATE + INTERVAL 14 DAY, '20:30:00',
   'Main Hall', 95, 'Invoice on completion', '85.00',
   'Livestream requested.', 'Amina Okonkwo', 'Microphones (4), Projector (1)', 'Technician, Usher'),

  (119045, 'Tom', 'Baker', '', 'Freelance', 'tom.baker@example.com',
   'Sonnenallee 5, 12047 Berlin', 'Team Retrospective',
   CURRENT_DATE - INTERVAL 5 DAY, '10:00:00', CURRENT_DATE - INTERVAL 5 DAY, '12:00:00',
   'Seminar Room B', 6, 'Paid in cash', '35.00', '', 'Tom Baker', 'Flipcharts (1)', ''),

  (462731, 'Sofia', 'Lindqvist', 'Dr.', 'Nordic Health e.V.', 'sofia.lindqvist@example.com',
   'Torstrasse 140, 10119 Berlin', 'Volunteer Training Day',
   CURRENT_DATE - INTERVAL 20 DAY, '09:30:00', CURRENT_DATE - INTERVAL 20 DAY, '15:30:00',
   'Seminar Room A', 30, 'Invoiced', '45.00', 'Catering handled externally.',
   'Sofia Lindqvist', 'Projector (1), Moderation Kit (1)', 'Usher');
