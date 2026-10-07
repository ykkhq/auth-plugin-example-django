"""Generates grafana/dashboards/kong-routes.json and kong-users.json.
Usage: python3 monitoring/grafana/generate_dashboards.py monitoring/grafana/dashboards"""
import json, sys, os
out = sys.argv[1]
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
_id = [0]
def nid():
    _id[0] += 1; return _id[0]

def target(ds, expr, legend="", instant=False, ref="A"):
    t = {"datasource": ds, "expr": expr, "refId": ref, "legendFormat": legend}
    if ds is LOKI:
        t["queryType"] = "instant" if instant else "range"
    else:
        t["instant"] = instant; t["range"] = not instant
    return t

def panel(ptype, title, ds, targets, x, y, w, h, unit=None, desc="", overrides=None, options=None, custom=None, thresholds=None, decimals=None):
    fc = {"defaults": {}, "overrides": overrides or []}
    if unit: fc["defaults"]["unit"] = unit
    if decimals is not None: fc["defaults"]["decimals"] = decimals
    if custom: fc["defaults"]["custom"] = custom
    fc["defaults"]["thresholds"] = thresholds or {"mode": "absolute", "steps": [{"color": "text", "value": None}]}
    fc["defaults"]["color"] = {"mode": "thresholds"} if ptype in ("stat",) else {"mode": "palette-classic"}
    p = {"id": nid(), "type": ptype, "title": title, "description": desc, "datasource": ds,
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets, "fieldConfig": fc}
    if options: p["options"] = options
    return p

def stat(title, ds, expr, x, y, unit=None, desc="", thresholds=None, decimals=None, instant=True):
    return panel("stat", title, ds, [target(ds, expr, instant=instant)], x, y, 6, 4, unit, desc,
                 options={"reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                          "colorMode": "value", "graphMode": "none", "textMode": "value"},
                 thresholds=thresholds, decimals=decimals)

TS_CUSTOM = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0, "showPoints": "never",
             "spanNulls": True, "axisSoftMin": 0}
TS_OPTS = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
           "tooltip": {"mode": "multi", "sort": "desc"}}
def ts(title, ds, targets, x, y, w=12, h=8, unit=None, desc="", overrides=None):
    return panel("timeseries", title, ds, targets, x, y, w, h, unit, desc, overrides, TS_OPTS, TS_CUSTOM)

def color_override(name_regex, color):
    return {"matcher": {"id": "byRegexp", "options": name_regex},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}
STATUS_OVERRIDES = [color_override("^2xx$", "green"), color_override("^3xx$", "blue"),
                    color_override("^4xx$", "orange"), color_override("^5xx$", "red")]

def bargauge(title, ds, expr, legend, x, y, w=8, h=8, desc="", unit=None):
    p = panel("bargauge", title, ds, [target(ds, expr, legend, instant=False)], x, y, w, h, unit, desc,
                 options={"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True,
                          "namePlacement": "top", "valueMode": "color", "sizing": "manual", "minVizHeight": 16, "maxVizHeight": 24,
                          "reduceOptions": {"calcs": ["lastNotNull"], "values": False}},
                 thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]})
    p["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": "blue"}
    p["maxDataPoints"] = 20
    return p

def dashboard(uid, title, desc, panels, templating):
    return {"uid": uid, "title": title, "description": desc, "tags": ["kong"],
            "timezone": "browser", "schemaVersion": 39, "version": 1, "editable": True,
            "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
            "templating": {"list": templating}, "panels": panels,
            "links": [{"type": "dashboards", "tags": ["kong"], "asDropdown": False, "title": "Kong dashboards"}]}

# ------------------------------------------------------------------ routes (Prometheus)
_id[0] = 0
R = 'route=~"$route", route!="kong-metrics-route"'
req = f'kong_http_requests_total{{{R}}}'
route_panels = [
    stat("Requests / s", PROM, f'sum(rate({req}[$__rate_interval]))', 0, 0, "reqps",
         "All selected routes, current rate.", decimals=2, instant=False),
    stat("Success rate", PROM,
         f'sum(rate(kong_http_requests_total{{{R}, code=~"[23].."}}[$__rate_interval])) / sum(rate({req}[$__rate_interval]))',
         6, 0, "percentunit", "Share of 2xx/3xx responses.",
         thresholds={"mode": "absolute", "steps": [{"color": "red", "value": None},
                     {"color": "orange", "value": 0.9}, {"color": "green", "value": 0.99}]}, decimals=1, instant=False),
    stat("Rate-limited (429) in range", PROM,
         f'sum(increase(kong_http_requests_total{{{R}, code="429"}}[$__range])) or vector(0)', 12, 0, "short",
         "Requests rejected by the per-user rate limit.", decimals=0),
    stat("p95 latency", PROM,
         f'histogram_quantile(0.95, sum by (le) (rate(kong_request_latency_ms_bucket{{{R}}}[$__rate_interval])))',
         18, 0, "ms", "Total request latency (Kong + upstream), 95th percentile.", decimals=0, instant=False),
    ts("Requests / s by route", PROM,
       [target(PROM, f'sum by (route) (rate({req}[$__rate_interval]))', "{{route}}")], 0, 4, unit="reqps"),
    ts("Responses by status class", PROM,
       [target(PROM, f'sum by (class) (label_replace(rate({req}[$__rate_interval]), "class", "${{1}}xx", "code", "(\\\\d).."))', "{{class}}")],
       12, 4, unit="reqps", overrides=STATUS_OVERRIDES),
    ts("p95 latency by route", PROM,
       [target(PROM, f'histogram_quantile(0.95, sum by (le, route) (rate(kong_request_latency_ms_bucket{{{R}}}[$__rate_interval])))', "{{route}}")],
       0, 12, unit="ms"),
    ts("p95 latency: Kong vs upstream (Django)", PROM,
       [target(PROM, f'histogram_quantile(0.95, sum by (le) (rate(kong_kong_latency_ms_bucket{{{R}}}[$__rate_interval])))', "Kong", ref="A"),
        target(PROM, f'histogram_quantile(0.95, sum by (le) (rate(kong_upstream_latency_ms_bucket{{{R}}}[$__rate_interval])))', "Upstream (Django)", ref="B")],
       12, 12, unit="ms", desc="Kong time includes OIDC work such as token requests to Auth0."),
    ts("Auth failures and rate limits by route", PROM,
       [target(PROM, f'sum by (route, code) (rate(kong_http_requests_total{{{R}, code=~"401|403|429"}}[$__rate_interval]))', "{{route}} · {{code}}")],
       0, 20, unit="reqps", desc="401 = no or invalid credentials, 403 = denied, 429 = per-user rate limit."),
    ts("Bandwidth by route", PROM,
       [target(PROM, f'sum by (route, direction) (rate(kong_bandwidth_bytes{{{R}}}[$__rate_interval]))', "{{route}} · {{direction}}")],
       12, 20, unit="Bps"),
]
route_vars = [{
    "name": "route", "label": "Route", "type": "query", "datasource": PROM,
    "query": {"query": 'label_values(kong_http_requests_total{route!="kong-metrics-route"}, route)', "refId": "route"},
    "definition": 'label_values(kong_http_requests_total{route!="kong-metrics-route"}, route)',
    "multi": True, "includeAll": True, "allValue": ".*", "refresh": 2, "sort": 1,
    "current": {"text": ["All"], "value": ["$__all"]}}]
d1 = dashboard("kong-routes", "Kong · Route activity",
               "Per-route traffic, status codes, latency and bandwidth from Kong's prometheus plugin.",
               route_panels, route_vars)

# ------------------------------------------------------------------ users (Loki)
_id[0] = 0
SEL = '{source="kong", route=~"$route"}'
B = f'{SEL} | json | user != "" | user =~ "$user"'
B429 = f'{{source="kong", route=~"$route", status_class="4"}} | json | response_status="429" | user =~ "$user"'
user_panels = [
    stat("Active users", LOKI, f'count(sum by (user) (count_over_time({B} [$__range])))', 0, 0, "short",
         "Distinct authenticated users (Auth0 sub) in the time range.", decimals=0),
    stat("Authenticated requests", LOKI, f'sum(count_over_time({B} [$__range]))', 6, 0, "short",
         "Requests made with a user identity in the time range.", decimals=0),
    stat("Rate-limited requests (429)", LOKI, f'sum(count_over_time({B429} [$__range]))', 12, 0, "short",
         "Requests rejected by the per-user rate limit.", decimals=0,
         thresholds={"mode": "absolute", "steps": [{"color": "text", "value": None}, {"color": "orange", "value": 1}]}),
    stat("Unauthenticated (401)", LOKI,
         f'sum(count_over_time({{source="kong", route=~"$route", status_class="4"}} | json | response_status="401" [$__range]))',
         18, 0, "short", "Requests without valid credentials (no user attached).", decimals=0,
         thresholds={"mode": "absolute", "steps": [{"color": "text", "value": None}, {"color": "orange", "value": 1}]}),
    ts("Requests per user", LOKI,
       [target(LOKI, f'topk(10, sum by (user) (count_over_time({B} [$__interval])))', "{{user}}")],
       0, 4, w=16, unit="short", desc="Top 10 users per interval."),
    bargauge("Top users (requests)", LOKI, f'topk(10, sum by (user) (count_over_time({B} [$__range])))',
             "{{user}}", 16, 4, w=8),
    ts("p95 latency per user", LOKI,
       [target(LOKI, f'quantile_over_time(0.95, {B} | unwrap latencies_request [$__interval]) by (user)', "{{user}}")],
       0, 12, w=12, unit="ms"),
    bargauge("Top rate-limited users (429)", LOKI, f'topk(10, sum by (user) (count_over_time({B429} [$__range])))',
             "{{user}}", 12, 12, w=6),
    bargauge("Unauthenticated (401) by client IP", LOKI,
             f'topk(10, sum by (client_ip) (count_over_time({{source="kong", route=~"$route", status_class="4"}} | json | response_status="401" [$__range])))',
             "{{client_ip}}", 18, 12, w=6),
    panel("table", "Requests by user, route and status", LOKI,
          [target(LOKI, f'sum by (user, route, response_status) (count_over_time({B} [$__range]))', instant=True)],
          0, 20, 24, 8, "short",
          options={"showHeader": True, "sortBy": [{"displayName": "Value", "desc": True}]},
          overrides=[]),
    panel("logs", "Recent authenticated requests", LOKI,
          [target(LOKI, B + ' | line_format "{{.user}}  {{.request_method}} {{.request_uri}} -> {{.response_status}}  {{.latencies_request}} ms  [{{.route_name}}]"')],
          0, 28, 24, 10, options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                                  "enableLogDetails": True}),
]
user_panels[9]["transformations"] = [{"id": "organize", "options": {
    "excludeByName": {"Time": True},
    "indexByName": {"user": 0, "route": 1, "response_status": 2, "Value #A": 3},
    "renameByName": {"user": "User", "route": "Route", "response_status": "Status", "Value #A": "Requests"}}}]
user_panels[9]["options"]["sortBy"] = [{"displayName": "Requests", "desc": True}]
user_vars = [
    {"name": "user", "label": "User (regex)", "type": "textbox", "query": ".*",
     "current": {"text": ".*", "value": ".*"}},
    {"name": "route", "label": "Route", "type": "query", "datasource": LOKI,
     "query": 'label_values({source="kong"}, route)',
     "definition": 'label_values({source="kong"}, route)', "multi": True, "includeAll": True, "allValue": ".*", "refresh": 2,
     "current": {"text": ["All"], "value": ["$__all"]}},
]
d2 = dashboard("kong-users", "Kong · User activity",
               "Per-user activity from Kong access logs. User = Auth0 token sub (openid-connect virtual credential).",
               user_panels, user_vars)

for name, d in (("kong-routes.json", d1), ("kong-users.json", d2)):
    with open(os.path.join(out, name), "w") as f:
        json.dump(d, f, indent=2)
print("ok")
