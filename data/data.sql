-- Datos totalmente sintéticos. Todos los importes están en centavos USD.
CREATE TABLE customers (customer_id TEXT PRIMARY KEY);
CREATE TABLE logins (
  event_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
  occurred_at TEXT NOT NULL
);
CREATE TABLE transactions (
  transaction_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers,
  occurred_at TEXT NOT NULL, amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('posted', 'reversed', 'pending'))
);
CREATE TABLE balances (
  customer_id TEXT NOT NULL REFERENCES customers, snapshot_date TEXT NOT NULL,
  balance_cents INTEGER NOT NULL, PRIMARY KEY (customer_id, snapshot_date)
);
INSERT INTO customers VALUES
  ('c01'), ('c02'), ('c03'), ('c04'), ('c05'), ('c06'),
  ('c07'), ('c08'), ('c09'), ('c10'), ('c11'), ('c12');
INSERT INTO logins VALUES
  ('l01', 'c01', '2026-10-20T12:00:00Z'),
  ('l02', 'c01', '2026-10-20T13:00:00Z'), -- mismo cliente, no cuenta dos veces
  ('l03', 'c02', '2026-10-19T12:00:00Z'),
  ('l04', 'c03', '2026-10-18T12:00:00Z'),
  ('l05', 'c04', '2026-10-17T12:00:00Z'),
  ('l06', 'c05', '2026-10-16T12:00:00Z'),
  ('l07', 'c06', '2026-10-15T12:00:00Z'),
  ('l08', 'c07', '2026-10-20T23:59:59Z'), -- dentro, justo antes del cierre
  ('l09', 'c08', '2026-09-21T00:00:00Z'), -- límite inferior incluido
  ('l10', 'c09', '2026-10-21T00:00:00Z'), -- límite superior excluido
  ('l11', 'c10', '2026-09-20T23:59:59Z'); -- fuera, justo antes del inicio
INSERT INTO transactions VALUES
  ('t01', 'c01', '2026-10-20T12:00:00Z', 1000, 'posted'),
  ('t02', 'c01', '2026-10-20T13:00:00Z', 2000, 'posted'),
  ('t03', 'c02', '2026-10-19T12:00:00Z', 1000, 'posted'),
  ('t04', 'c03', '2026-10-20T23:59:59Z', 1000, 'posted'),
  ('t05', 'c04', '2026-09-21T00:00:00Z', 1000, 'posted'),
  ('t06', 'c05', '2026-10-18T12:00:00Z', -700, 'posted'), -- reembolso sí cuenta
  ('t07', 'c06', '2026-10-21T00:00:00Z', 1000, 'posted'),
  ('t08', 'c07', '2026-10-17T12:00:00Z', 0, 'posted'),
  ('t09', 'c08', '2026-10-16T12:00:00Z', 1000, 'reversed'),
  ('t10', 'c09', '2026-10-15T12:00:00Z', 1000, 'pending'),
  ('t11', 'c10', '2026-09-20T23:59:59Z', 1000, 'posted');
INSERT INTO balances VALUES
  ('c01', '2026-10-20', 5000), ('c02', '2026-10-20', 0),
  ('c03', '2026-10-20', -100), ('c04', '2026-10-20', 0),
  ('c05', '2026-10-20', 0), ('c06', '2026-10-20', 8000),
  ('c07', '2026-10-20', 0), ('c08', '2026-10-20', 0),
  ('c09', '2026-10-20', 0), ('c10', '2026-10-20', 300),
  ('c11', '2026-10-20', 0), ('c12', '2026-10-20', 0),
  ('c04', '2026-10-19', 9000), -- otra fecha: no cuenta
  ('c02', '2026-10-21', 9000); -- otra fecha: no cuenta
