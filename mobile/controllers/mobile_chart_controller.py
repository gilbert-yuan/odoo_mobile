# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from ..models.mobile_model import _json_response, _literal, _split_names


class MobileChartController(http.Controller):
    @http.route("/odoo/mobile/charts/config", auth="user", type="http", methods=["GET"], csrf=False)
    def mobile_chart_configs(self, **args):
        charts = request.env["mobile.chart.config"].sudo().search([("active", "=", True)])
        users = request.env["res.users"].sudo().search([("active", "=", True)])
        user_options = [{"key": 0, "value": "全部人员"}] + [{"key": user.id, "value": user.name} for user in users]
        return _json_response({"charts": [chart.chart_payload() for chart in charts], "users": user_options})

    def _chart_groupby_expr(self, chart):
        if chart.group_by == "month":
            return "%s:month" % chart.date_field_name
        if chart.group_by == "week":
            return "%s:week" % chart.date_field_name
        if chart.group_by == "day":
            return "%s:day" % chart.date_field_name
        if chart.group_by == "person":
            return chart.person_field_name
        return "%s:month" % chart.date_field_name

    def _chart_domain(self, chart, date_start="", date_end="", user_id=0):
        domain = _literal(chart.base_domain, [])
        is_datetime = chart.date_field_id.ttype == "datetime"
        start_value = date_start
        end_value = date_end
        if is_datetime and date_start and len(date_start) == 10:
            start_value = "%s 00:00:00" % date_start
        if is_datetime and date_end and len(date_end) == 10:
            end_value = "%s 23:59:59" % date_end
        if date_start:
            domain.append((chart.date_field_name, ">=", start_value))
        if date_end:
            domain.append((chart.date_field_name, "<=", end_value))
        if user_id and chart.person_field_name:
            domain.append((chart.person_field_name, "=", int(user_id)))
        done_values = _split_names(chart.done_states)
        if chart.state_field and done_values:
            domain.append((chart.state_field, "in", done_values))
        return domain

    def _chart_measure_expr(self, chart):
        if chart.measure_type == "count":
            return "id:count", "id_count"
        return "%s:%s" % (chart.measure_field_name, chart.measure_type), chart.measure_field_name

    def _chart_value(self, row, chart, value_key):
        if chart.measure_type == "count":
            value = row.get(value_key, row.get("__count", 0))
        else:
            value = row.get(value_key, row.get(chart.measure_field_name))
        return float(value or 0)

    def _chart_label(self, row, chart):
        key = self._chart_groupby_expr(chart)
        raw = row.get(key)
        if chart.group_by == "person":
            if isinstance(raw, (list, tuple)) and raw:
                return raw[1]
            return "未分配"
        if isinstance(raw, str):
            return raw[:10]
        return str(raw or "")

    def _chart_series(self, chart, date_start="", date_end="", user_id=0):
        model = request.env[chart.model_name].sudo()
        group_expr = self._chart_groupby_expr(chart)
        measure_expr, value_key = self._chart_measure_expr(chart)
        domain = self._chart_domain(chart, date_start=date_start, date_end=date_end, user_id=user_id)
        rows = model.read_group(domain, [measure_expr], [group_expr], lazy=False)
        labels = []
        values = []
        for row in rows:
            labels.append(self._chart_label(row, chart))
            values.append(self._chart_value(row, chart, value_key))
        if chart.measure_type == "avg" and values:
            values = [round(item, 2) for item in values]
        return {"labels": labels, "values": values}

    @http.route("/odoo/mobile/charts/data", auth="user", type="http", methods=["GET"], csrf=False)
    def mobile_chart_data(self, **args):
        date_start = (args.get("date_start") or "").strip()
        date_end = (args.get("date_end") or "").strip()
        user_id = int(args.get("user_id") or 0)
        configs = request.env["mobile.chart.config"].sudo().search([("active", "=", True)])
        charts = []
        for chart in configs:
            if not chart.model_name or not chart.date_field_name:
                continue
            if chart.measure_type in ("sum", "avg") and not chart.measure_field_name:
                continue
            if chart.group_by == "person" and not chart.person_field_name:
                continue
            series = self._chart_series(chart, date_start=date_start, date_end=date_end, user_id=user_id)
            charts.append({**chart.chart_payload(), **series})
        return _json_response({"charts": charts})
