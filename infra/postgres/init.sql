-- PITWALL — PostgreSQL: cadastro de dispositivos, regras, alertas e auditoria.
-- (As leituras/telemetria ficam no InfluxDB.)

create table if not exists devices (
    id          text primary key,                 -- ex.: PW16, PW16.tyre_temp_FL
    kind        text not null check (kind in ('car', 'equipment', 'sensor', 'actuator')),
    name        text not null,
    car_id      text,                              -- carro ao qual pertence
    component   text,                              -- peça 3D (tyre_FL, pu, fuel_cell...) — mesmo id no frontend
    field       text,                              -- campo da telemetria
    unit        text,
    normal_min  double precision,
    normal_max  double precision,
    crit_min    double precision,
    crit_max    double precision,
    control     text check (control in ('web', 'auto', 'rule', null)),
    metadata    jsonb not null default '{}'::jsonb,
    enabled     boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists devices_car_idx on devices (car_id);

create table if not exists rules (
    id              serial primary key,
    name            text not null unique,
    field           text not null,
    op              text not null check (op in ('>', '<')),
    threshold       double precision not null,
    clear_threshold double precision not null,
    on_count        int not null default 3,       -- histerese: leituras seguidas para disparar
    off_count       int not null default 10,      -- leituras seguidas para limpar
    severity        text not null check (severity in ('info', 'warning', 'critical')),
    action_on       jsonb,                         -- comando enviado ao disparar
    action_off      jsonb,                         -- comando enviado ao limpar
    team_only       boolean not null default false,
    message         text not null,
    enabled         boolean not null default true
);

create table if not exists alerts (
    id          bigserial primary key,
    car_id      text not null,
    rule_id     int references rules (id) on delete set null,
    field       text,
    severity    text not null,
    message     text not null,
    value       double precision,
    raised_at   timestamptz not null default now(),
    cleared_at  timestamptz
);
create index if not exists alerts_open_idx on alerts (car_id) where cleared_at is null;

create table if not exists audit_log (
    id       bigserial primary key,
    ts       timestamptz not null default now(),
    actor    text not null,
    action   text not null,
    target   text,
    details  jsonb not null default '{}'::jsonb
);
create index if not exists audit_ts_idx on audit_log (ts desc);

-- Etapa 2 (JWT + papéis). Criada agora para o modelo de dados ficar completo.
create table if not exists users (
    id            serial primary key,
    username      text not null unique,
    password_hash text not null,
    role          text not null check (role in ('viewer', 'operator', 'admin')),
    created_at    timestamptz not null default now()
);

-- ------------------------------------------------------------------ seeds
insert into devices (id, kind, name, car_id, component, metadata) values
    ('PW16', 'car', 'Pitwall Racing #16 — L. Moreau', 'PW16', 'chassis', '{"team":"Pitwall Racing","number":16,"driver":"L. Moreau","team_car":true}'),
    ('PW55', 'car', 'Pitwall Racing #55 — K. Sato',   'PW55', 'chassis', '{"team":"Pitwall Racing","number":55,"driver":"K. Sato","team_car":true}'),
    ('AU01', 'car', 'Aurora GP #1 — D. Varga',        'AU01', 'chassis', '{"team":"Aurora GP","number":1,"driver":"D. Varga","team_car":false}'),
    ('AU44', 'car', 'Aurora GP #44 — M. Okafor',      'AU44', 'chassis', '{"team":"Aurora GP","number":44,"driver":"M. Okafor","team_car":false}'),
    ('VX07', 'car', 'Vortex Motorsport #7 — R. Lindqvist', 'VX07', 'chassis', '{"team":"Vortex Motorsport","number":7,"driver":"R. Lindqvist","team_car":false}'),
    ('VX23', 'car', 'Vortex Motorsport #23 — T. Ferraz',   'VX23', 'chassis', '{"team":"Vortex Motorsport","number":23,"driver":"T. Ferraz","team_car":false}')
on conflict do nothing;

with cars as (select id from devices where kind = 'car'),
wheels(w) as (values ('FL'), ('FR'), ('RL'), ('RR')),
tpl(kind, field, name, unit, component, nmin, nmax, cmin, cmax, control) as (
    values
    ('equipment', null,           'Power Unit (equipamento monitorado)', null, 'pu',        null, null, null, null, null),
    ('sensor',    'speed_kph',    'Velocidade',               'km/h', 'chassis',   0,    350,  null, null, null),
    ('sensor',    'rpm',          'Rotação do motor',          'rpm',  'pu',        0,    12200, null, 12600, null),
    ('sensor',    'engine_temp',  'Temperatura do motor',      '°C',   'pu',        80,   112,  null, 118, null),
    ('sensor',    'oil_temp',     'Temperatura do óleo',       '°C',   'pu',        80,   112,  null, 122, null),
    ('sensor',    'oil_pressure', 'Pressão do óleo',           'bar',  'pu',        4.2,  7,    3.2,  null, null),
    ('sensor',    'pu_vibration', 'Vibração da PU',            'g',    'pu',        0,    1.4,  null, 2.2, null),
    ('sensor',    'fuel_kg',      'Combustível',               'kg',   'fuel_cell', 12,   110,  4,    null, null),
    ('sensor',    'ers_soc',      'Bateria ERS',               '%',    'ers',       20,   100,  5,    null, null),
    ('actuator',  'engine_mode',  'Modo do motor',             null,   'pu',        null, null, null, null, 'web'),
    ('actuator',  'ers_mode',     'Modo ERS',                  null,   'ers',       null, null, null, null, 'web'),
    ('actuator',  'box_requested','Chamada para o box',        null,   'chassis',   null, null, null, null, 'web'),
    ('actuator',  'cooling',      'Resfriamento / lift-and-coast', null, 'radiator', null, null, null, null, 'rule'),
    ('actuator',  'drs',          'DRS (asa móvel)',           null,   'rear_wing', null, null, null, null, 'auto')
)
insert into devices (id, kind, name, car_id, component, field, unit, normal_min, normal_max, crit_min, crit_max, control)
select c.id || '.' || coalesce(t.field, t.component), t.kind, t.name, c.id, t.component, t.field, t.unit,
       t.nmin, t.nmax, t.cmin, t.cmax, t.control
from cars c cross join tpl t
on conflict do nothing;

with cars as (select id from devices where kind = 'car'),
wheels(w) as (values ('FL'), ('FR'), ('RL'), ('RR')),
tpl(kind, prefix, name, unit, comp, nmin, nmax, cmin, cmax) as (
    values
    ('equipment', null,         'Pneu',                null,  'tyre_',  null, null, null, null),
    ('sensor',    'tyre_temp_',  'Temperatura do pneu', '°C',  'tyre_',  80,   110,  65,   125),
    ('sensor',    'tyre_wear_',  'Desgaste do pneu',    '%',   'tyre_',  0,    60,   null, 80),
    ('sensor',    'tyre_press_', 'Pressão do pneu',     'psi', 'tyre_',  18,   24,   15,   null),
    ('sensor',    'brake_temp_', 'Temperatura do freio','°C',  'brake_', 200,  900,  null, 1050)
)
insert into devices (id, kind, name, car_id, component, field, unit, normal_min, normal_max, crit_min, crit_max)
select c.id || '.' || coalesce(t.prefix, t.comp) || w.w, t.kind, t.name || ' ' || w.w, c.id, t.comp || w.w,
       case when t.prefix is null then null else t.prefix || w.w end, t.unit, t.nmin, t.nmax, t.cmin, t.cmax
from cars c cross join wheels w cross join tpl t
on conflict do nothing;

insert into rules (name, field, op, threshold, clear_threshold, on_count, off_count, severity, action_on, action_off, team_only, message) values
    ('Resfriamento automático', 'engine_temp', '>', 118, 108, 5, 20, 'warning',
        '{"action":"cooling","value":true}', '{"action":"cooling","value":false}', false,
        '{car}: motor a {value} °C (> {threshold} °C) — resfriamento / lift-and-coast ativado'),
    ('Janela de pit (desgaste)', 'tyre_wear_max', '>', 70, 5, 3, 3, 'warning', null, null, true,
        '{car}: pneu com {value}% de desgaste — janela de pit aberta'),
    ('Pneu no cliff', 'tyre_wear_max', '>', 85, 5, 3, 3, 'critical', null, null, true,
        '{car}: pneu com {value}% — perda severa de aderência, BOX imediato'),
    ('Vibração anormal da PU', 'pu_vibration', '>', 2.0, 1.5, 10, 30, 'critical', null, null, false,
        '{car}: vibração da PU em {value} g — possível desgaste de rolamento'),
    ('Pressão do óleo baixa', 'oil_pressure', '<', 3.5, 4.2, 10, 30, 'critical', null, null, false,
        '{car}: pressão do óleo em {value} bar'),
    ('Furo lento', 'tyre_press_min', '<', 16, 18, 5, 10, 'critical', null, null, false,
        '{car}: pressão de um pneu caiu para {value} psi — furo lento'),
    ('Combustível baixo', 'fuel_kg', '<', 12, 20, 5, 5, 'warning', null, null, true,
        '{car}: restam {value} kg de combustível')
on conflict do nothing;

insert into audit_log (actor, action, target, details) values ('system', 'bootstrap', 'database', '{"seed":true}');
