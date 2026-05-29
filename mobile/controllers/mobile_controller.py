# -*- coding: utf-8 -*-
import base64
import copy
import datetime
import json
import mimetypes
import os

import jinja2

from odoo import fields, http
from odoo.addons.web.controllers.utils import ensure_db
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools.float_utils import float_round

from ..models.mobile_model import (
    ISODATEFORMAT,
    ISODATETIMEFORMAT,
    MOBILEDATETIMEFORMAT,
    _error_message,
    _format_mobile_default_value,
    _is_visible_one2many_field,
    _json_request_payload,
    _json_response,
    _literal,
    _name_get,
    _or_domain,
    _split_names,
)

STATIC_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'static'))
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(STATIC_PATH),
    autoescape=True,
)

VIEW_TYPE = {
    "tree": "Tree",
    "card": "OdooCard",
}


class MobileController(http.Controller):
    @http.route(
        ["/odoo/mobile", "/mobile/html", "/mobile/html/", "/mobile/html/index.html"],
        auth="public",
        type="http",
    )
    def odoo_mobile(self, **kwargs):
        template = env.get_template("html/index.html")
        return request.make_response(
            template.render(),
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )

    @http.route("/odoo/mobile/get/all/grid_data", auth="user", type="http", methods=["GET"], csrf=False)
    def get_all_grid_data(self, **kwargs):
        grouped = {}
        for grid in request.env["mobile.grid"].sudo().search([]):
            image = grid.image or b""
            if isinstance(image, str):
                image_data = image
            else:
                image_data = base64.b64encode(image).decode()
            grouped.setdefault(grid.label_id, []).append(
                {
                    "title": grid.title,
                    "actionId": grid.mobile_action_id.id,
                    "image": "data:image/png;base64,%s" % image_data if image_data else "",
                }
            )

        grid_list = [
            {
                "groupTitle": label.name,
                "sequence": label.sequence,
                "gridCols": 4,
                "gridRow": row,
            }
            for label, row in grouped.items()
        ]
        return _json_response(sorted(grid_list, key=lambda grid: grid.get("sequence") or 0))

    @http.route("/odoo/mobile/get/action/views", auth="user", type="http", methods=["GET"], csrf=False)
    def get_action_views(self, **args):
        action = request.env["mobile.action"].sudo().browse(int(args.get("actionId", 0)))
        view = action.mobile_view_id
        views_data = sorted(
            [
                {"title": domain.name, "sequence": domain.sequence, "domain": domain.domain}
                for domain in view.domain_ids
            ],
            key=lambda item: item.get("sequence") or 0,
        )
        return _json_response(
            {
                "title": action.name,
                "modelID": action.model_id.id,
                "view_id": view.id,
                "noForm": view.no_form,
                "model": action.model_id.model,
                "limit": action.limit or 6,
                "offset": action.offset or 6,
                "order": action.order or "id DESC",
                "context": view.context or "{}",
                "viewsData": views_data,
                "view_type": VIEW_TYPE.get(view.view_type, "Tree"),
            }
        )

    @http.route("/odoo/mobile/get/list/view/data", auth="user", type="http", methods=["GET"], csrf=False)
    def get_action_form_pre_view(self, **args):
        model_name = args.get("model")
        if not model_name:
            return _json_response([])

        offset = int(args.get("offset", "0"))
        limit = int(args.get("limit", "0"))
        order = args.get("order", "id DESC")
        domain = _literal(args.get("domain"), [])
        keyword = (args.get("keyword") or "").strip()
        keyword_fields = _literal(args.get("keyword_fields"), [])
        if not isinstance(keyword_fields, (list, tuple, str)):
            keyword_fields = []
        keyword_fields = _split_names(keyword_fields) or ["display_name"]
        if keyword:
            domain = list(domain) + _or_domain(keyword_fields, "ilike", keyword)
        view_id = int(args.get("view_id", "0"))
        records = request.env[model_name].sudo().search(domain, offset=offset, limit=limit, order=order)
        view = request.env["mobile.view"].sudo().browse(view_id)
        handler = self.get_view_type_function(view.view_type)
        return _json_response(handler(view, records, model_name) if handler else [])

    def get_view_type_function(self, view_type):
        return {
            "card": self.get_card_view_data,
            "tree": self.get_tree_view_data,
        }.get(view_type)

    def get_all_field_setting(self, field):
        return {
            "title": field.ir_field.field_description,
            "type": field.field_type,
            "value": "",
            "required": field.required,
            "readonly": field.readonly,
            "invisible": field.invisible,
            "group": field.group_name or "",
            "groupCollapsed": field.group_collapsed,
            "summaryVisible": field.summary_visible,
            "summaryPriority": field.summary_priority or 10,
            "summaryStyle": field.summary_style or "auto",
            "name": field.ir_field.name,
            "fieldId": field.id,
            "widget": False if field.widget == "auto" else field.widget,
            "placeholder": field.placeholder or "",
            "relationLimit": field.relation_limit or 20,
            "searchFields": _split_names(field.relation_search_fields),
            "allowQuickCreate": field.allow_quick_create,
            "filenameField": field.binary_filename_field or "",
            "accept": field.binary_accept or ("image/*" if field.widget == "image" else ""),
            "maxSizeMb": field.binary_max_size_mb or 8,
            "imageMaxWidth": field.image_max_width or 1600,
            "imageQuality": field.image_quality or 0.86,
            "searchable": field.selection_searchable,
            "min": field.number_min,
            "max": field.number_max,
            "step": field.number_step or 1,
        }

    def _view_mobile_options(self, view):
        return {
            "fieldLayout": view.field_layout or "auto",
            "fieldAutoLimit": view.field_auto_limit or 8,
            "summaryLimit": view.summary_limit or 3,
            "buttonLimit": view.button_limit or 3,
            "buttonCollapse": view.button_collapse,
        }

    def _button_style(self, button):
        if button.button_style and button.button_style != "auto":
            return button.button_style
        return "danger" if button.button_method == "unlink" else "secondary"

    def _button_field(self, button, model_name, records):
        domain = _literal(button.show_condition, []) + [("id", "in", records.ids)]
        matching = request.env[model_name].sudo().search(domain)
        view = button.view_id
        return {
            "title": button.name,
            "type": "button",
            "value": button.button_method,
            "group": button.button_group or "",
            "sequence": button.sequence,
            "user_ids": [user.id for group in button.group_ids for user in group.users],
            "model": model_name,
            "ids": matching.ids,
            "style": self._button_style(button),
            "icon": button.button_icon or "",
            "folded": button.button_folded or button.button_method == "unlink",
            "confirm": button.button_confirm or ("确认删除这条记录？" if button.button_method == "unlink" else ""),
            "buttonLimit": view.button_limit or 3,
            "buttonCollapse": view.button_collapse,
            "invisible": button.show_condition,
        }

    def get_tree_view_data(self, view, records, model_name):
        fields_config = [self.get_all_field_setting(field) for field in view.mobile_field_ids]
        fields_config += [self._button_field(button, model_name, records) for button in view.button_ids]
        rows = []
        for record in records:
            row_fields = copy.deepcopy(fields_config)
            for field in row_fields:
                field.update(self.card_show_val(record, field))
            rows.append(
                {
                    "title": record.display_name,
                    "id": record.id,
                    "meta": row_fields,
                    "mobileOptions": self._view_mobile_options(view),
                }
            )
        return rows

    def get_card_view_data(self, view, records, model_name):
        fields_config = [self.get_all_field_setting(field) for field in view.mobile_field_ids]
        fields_config += [self._button_field(button, model_name, records) for button in view.button_ids]
        rows = []
        for record in records:
            row_fields = copy.deepcopy(fields_config)
            for field in row_fields:
                field.update(self.card_show_val(record, field))
            rows.append({"fieldVals": row_fields, "id": record.id, "mobileOptions": self._view_mobile_options(view)})
        return rows

    def card_show_val(self, record, field):
        field_type = field.get("type")
        if field_type == "many2one":
            options = self.card_field_type_get_val(field, record)
            return {"options": options, "value": options[0]["key"] if options else ""}
        if field_type == "many2many":
            options = self.card_field_type_get_val(field, record)
            return {"options": options, "value": [option["key"] for option in options]}
        if field_type == "button":
            ids = field.get("ids") or []
            users = field.get("user_ids") or []
            return {"invisible": record.id not in ids or (users and request.uid not in users)}
        if field_type == "one2many":
            value, ids = self.get_show_tree_one2many(record, field)
            return {"value": value, "ids": ids, "table": self.get_record_one2many(record, field)}
        if field_type == "binary":
            return self.card_field_type_get_val(field, record)
        if field_type == "selection":
            value = self.card_field_type_get_val(field, record)
            selection = record._fields[field.get("name")].selection
            return {
                "value": value,
                "options": [{"key": key, "value": label} for key, label in selection],
            }
        return {"value": self.card_field_type_get_val(field, record)}

    def get_show_tree_one2many(self, record, field):
        rows = []
        ids = []
        many_fields = [item for item in field.get("many_field", []) if _is_visible_one2many_field(item)]
        if not (many_fields and field.get("name")):
            return [], []
        for line in record[field.get("name")]:
            ids.append(line.id)
            row_fields = copy.deepcopy(many_fields)
            for row_field in row_fields:
                row_field.update(self.card_show_val(line, row_field))
            rows.append({"title": line.display_name, "id": line.id, "meta": row_fields})
        return rows, ids

    def card_field_type_get_val(self, field, record):
        field_type = field.get("type")
        value = record[field.get("name")]
        if value is False or value is None:
            return False if field_type == "boolean" else ""
        if field_type in ("char", "text", "boolean", "integer"):
            return value
        if field_type in ("html", "json", "properties", "serialized"):
            return value
        if field_type == "reference":
            return getattr(value, "display_name", False) or str(value)
        if field_type == "many2one":
            name = _name_get(value)
            return [{"key": name[0][0], "value": name[0][1]}] if name else []
        if field_type == "many2many":
            return [{"key": item[0], "value": item[1]} for item in _name_get(value)]
        if field_type == "binary":
            if isinstance(value, bytes):
                value = value.decode()
            filename = ""
            filename_field = field.get("filenameField")
            if filename_field and filename_field in record._fields:
                filename = record[filename_field] or ""
            mimetype = mimetypes.guess_type(filename)[0] or ("image/png" if field.get("widget") == "image" else "application/octet-stream")
            return {"value": value, "filename": filename, "mimetype": mimetype, "filesize": len(value or "")}
        if field.get("widget") == "float_time":
            return float_round(value, precision_digits=2)
        if field_type == "date":
            date_obj = fields.Date.to_date(value)
            return date_obj.strftime(ISODATEFORMAT) if date_obj else ""
        if field_type == "datetime":
            date_obj = fields.Datetime.to_datetime(value)
            return date_obj.strftime(MOBILEDATETIMEFORMAT) if date_obj else ""
        if field_type in ("float", "monetary"):
            return float_round(value, precision_digits=2)
        if field_type == "selection":
            return value
        return ""

    def get_record_one2many(self, record, field):
        many_fields = [item for item in field.get("many_field", []) if _is_visible_one2many_field(item)]
        if not (many_fields and field.get("name")):
            return {}
        table_header = [son_field.get("title") for son_field in many_fields]
        table_body = []
        for line in record[field.get("name")]:
            row_fields = copy.deepcopy(many_fields)
            for row_field in row_fields:
                row_field.update(self.card_show_val(line, row_field))
            table_body.append(row_fields)
        return {"tableTh": table_header, "tableBody": table_body}

    @http.route("/odoo/mobile/button/method", auth="user", type="http", methods=["GET"], csrf=False)
    def mobile_button_method(self, **args):
        model = args.get("model")
        method = args.get("method")
        ids = int(args.get("ids") or 0)
        record = request.env[model].sudo().browse(ids)
        if not (record and hasattr(record, method) and ids):
            return _json_response({"success": False, "errMsg": "无效操作"})
        try:
            if method == "unlink":
                getattr(record, method)()
            else:
                getattr(record, method)()
            return _json_response({"success": True})
        except Exception as exc:
            return _json_response({"success": False, "errMsg": _error_message(exc)})

    def get_many_field_value(self, field):
        field_value = self.get_all_field_setting(field)
        if field.field_type in ("many2one", "many2many"):
            field_value.update({"model": field.ir_field.relation, "domain": field.domain or "[]", "options": []})
        return field_value

    def set_default_val(self, field_value, default_val):
        name = field_value.get("name")
        field_type = field_value.get("type")
        if name not in default_val:
            return {}
        value = default_val.get(name)
        if value in (None, "") or (value is False and field_type != "boolean"):
            return {}
        if field_type == "many2one":
            option = _name_get(request.env[field_value.get("model")].browse(value))
            return {
                "value": value,
                "options": [{"key": item[0], "value": item[1]} for item in option],
            }
        return {"value": _format_mobile_default_value(field_value, value)}

    def get_form_view_data(self, view, record_id, model_name):
        view = view or request.env["mobile.view"]
        fields_config = []
        default_val = request.env[model_name].sudo().default_get([field.ir_field.name for field in view.mobile_field_ids])
        for field in view.mobile_field_ids:
            field_value = self.get_all_field_setting(field)
            if field.field_type in ("many2one", "many2many"):
                field_value.update({"model": field.ir_field.relation, "domain": field.domain or "[]", "options": []})
            if field.field_type == "selection":
                selection = request.env[model_name]._fields[field_value.get("name")].selection
                field_value.update({"options": [{"key": key, "value": label} for key, label in selection]})
            if field.field_type == "one2many":
                field_value.update(
                    {
                        "many_field": [
                            self.get_many_field_value(child_field)
                            for child_field in field.many_field
                            if _is_visible_one2many_field(child_field)
                        ],
                        "value": [],
                    }
                )
            field_value.update(self.set_default_val(field_value, default_val))
            fields_config.append(field_value)

        record = request.env[model_name].sudo().browse(record_id)
        for button in view.button_ids:
            domain = _literal(button.show_condition, []) + [("id", "=", record_id)]
            matching = request.env[model_name].sudo().search(domain)
            fields_config.append(
                {
                    "title": button.name,
                    "type": "button",
                    "value": button.button_method,
                    "group": button.button_group or "",
                    "sequence": button.sequence,
                    "user_ids": [user.id for group in button.group_ids for user in group.users],
                    "model": model_name,
                    "ids": matching.ids,
                    "style": self._button_style(button),
                    "icon": button.button_icon or "",
                    "folded": button.button_folded or button.button_method == "unlink",
                    "confirm": button.button_confirm or ("确认删除这条记录？" if button.button_method == "unlink" else ""),
                    "buttonLimit": view.button_limit or 3,
                    "buttonCollapse": view.button_collapse,
                    "invisible": button.show_condition,
                }
            )

        if record.exists():
            record_fields = copy.deepcopy(fields_config)
            for field in record_fields:
                field.update(self.card_show_val(record, field))
            return {"fieldVals": record_fields, "id": record.id, "mobileOptions": self._view_mobile_options(view)}
        return {"fieldVals": fields_config, "id": 0, "mobileOptions": self._view_mobile_options(view)}

    @http.route("/odoo/mobile/form/view/data", auth="user", type="http", methods=["GET"], csrf=False)
    def get_odoo_view_data(self, **args):
        model_name = args.get("model", "")
        view_id = int(args.get("viewId", "0"))
        record_id = int(args.get("id", "0"))
        view = request.env["mobile.view"].sudo().browse(view_id)
        form_view = view.show_form_view or view
        return _json_response(self.get_form_view_data(form_view, record_id, model_name) if model_name else {})

    @http.route("/odoo/mobile/model/name_search", auth="user", type="http", methods=["GET"], csrf=False)
    def get_odoo_model_name_search(self, **args):
        model_name = args.get("model")
        limit = int(args.get("limit", "15"))
        value = args.get("value", "")
        domain = _literal(args.get("domain"), [])
        search_fields = _literal(args.get("search_fields"), [])
        model = request.env[model_name].sudo()
        if value and search_fields:
            records = model.search(domain + _or_domain(search_fields, "ilike", value), limit=limit)
            result = _name_get(records)
        elif value:
            result = model.name_search(name=value, operator="ilike", args=domain, limit=limit)
        else:
            records = model.search(domain, limit=limit)
            result = _name_get(records)
        return _json_response([{"key": item[0], "value": item[1]} for item in result])

    @http.route("/odoo/mobile/model/name_create", auth="user", type="json", csrf=False)
    def mobile_model_name_create(self, **args):
        payload = _json_request_payload(args)
        model_name = payload.get("model")
        name = (payload.get("name") or "").strip()
        values = payload.get("values") or {}
        if not model_name or not name:
            return {"success": False, "errMsg": "缺少模型或名称"}
        field_config = request.env["mobile.field"].sudo().browse(int(payload.get("field_id") or 0))
        if not field_config.exists() or not field_config.allow_quick_create or field_config.ir_field.relation != model_name:
            return {"success": False, "errMsg": "未开启快速创建"}
        try:
            model = request.env[model_name]
            rec_name = model._rec_name or "name"
            values[rec_name] = name
            record = model.create(values)
            return {"success": True, "option": {"key": record.id, "value": record.display_name}}
        except Exception as exc:
            return {"success": False, "errMsg": _error_message(exc)}

    def _mobile_api_payload(self, args):
        if request.httprequest.method == "GET":
            return dict(args)
        try:
            return json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except ValueError:
            return dict(args)

    @http.route(
        ["/odoo/mobile/api/<string:code>"],
        auth="public",
        type="http",
        methods=["GET", "POST"],
        csrf=False,
    )
    def mobile_config_api(self, code, **args):
        config = request.env["mobile.api.config"].sudo().search([("code", "=", code)], limit=1)
        if not config:
            return _json_response({"success": False, "errMsg": "接口不存在"})
        payload = self._mobile_api_payload(args)
        try:
            return _json_response(config.execute_mobile_api(payload))
        except Exception as exc:
            return _json_response({"success": False, "errMsg": _error_message(exc)})

    def construct_model_vals(self, record_id, vals):
        data = {}
        for val in vals:
            value = val.get("value")
            field_type = val.get("type")
            field_name = val.get("name")
            if field_name == "id":
                continue
            widget = val.get("widget")
            if value in (None, ""):
                if field_type in ("many2one", "date", "datetime", "selection", "char", "text", "html", "binary", "json", "properties", "serialized", "reference"):
                    data[field_name] = False
                    filename_field = val.get("filenameField")
                    if field_type == "binary" and filename_field:
                        data[filename_field] = False
                continue
            if widget == "float_time":
                data[field_name] = float(value)
            elif field_type in ("text", "char", "html", "date", "selection"):
                data[field_name] = value
            elif field_type == "datetime":
                if isinstance(value, str) and "T" in value:
                    value = value.replace("T", " ")
                if isinstance(value, str) and len(value) == 16:
                    value = "%s:00" % value
                date_obj = datetime.datetime.strptime(value, ISODATETIMEFORMAT)
                data[field_name] = fields.Datetime.to_string(date_obj)
            elif widget == "time":
                data[field_name] = value
            elif field_type in ("integer", "many2one"):
                data[field_name] = int(value)
            elif field_type in ("float", "monetary"):
                data[field_name] = float(value)
            elif field_type == "boolean":
                data[field_name] = bool(value)
            elif field_type in ("json", "properties", "serialized"):
                data[field_name] = _literal(value, value)
            elif field_type == "reference":
                data[field_name] = value
            elif field_type == "binary":
                data[field_name] = value
                filename_field = val.get("filenameField")
                if filename_field and val.get("filename"):
                    data[filename_field] = val.get("filename")
            elif field_type == "one2many":
                commands = []
                next_ids = []
                origin_ids = val.get("ids") or []
                for line_val in value:
                    line_id = line_val.get("id")
                    next_ids.append(line_id)
                    row = {
                        field.get("name"): field.get("value")
                        for field in line_val.get("meta", [])
                        if field.get("name") and field.get("name") != "id"
                        and _is_visible_one2many_field(field)
                    }
                    for field in line_val.get("meta", []):
                        if field.get("type") == "binary" and field.get("filenameField"):
                            row[field.get("filenameField")] = field.get("filename") or False
                    commands.append((1, line_id, row) if record_id and line_id else (0, 0, row))
                for delete_id in set(origin_ids) - set(next_ids):
                    commands.append((2, delete_id, False))
                data[field_name] = commands
            elif field_type == "many2many":
                data[field_name] = [(6, 0, value or [])]
        return data

    @http.route("/odoo/mobile/save/record", auth="user", type="json", csrf=False)
    def create_new_record(self, **args):
        payload = _json_request_payload(args)
        model = payload.get("model")
        vals = payload.get("value") or []
        record_id = int(payload.get("id") or 0)
        context_val = _literal(payload.get("context"), {})
        if not model:
            return {"success": False, "errMsg": "缺少模型名称"}
        if not isinstance(vals, list):
            return {"success": False, "errMsg": "提交数据格式错误"}
        data = self.construct_model_vals(record_id, vals)

        try:
            if not record_id:
                data.update(context_val.get("default_vals", {}))
                request.env[model].sudo().create(data)
                return {"success": True, "errMsg": "创建成功！"}
            request.env[model].sudo().browse(record_id).write(data)
            return {"success": True, "errMsg": "修改成功！"}
        except Exception as exc:
            return {"success": False, "errMsg": _error_message(exc)}

    @http.route("/odoo/mobile/login", auth="public", type="json", csrf=False)
    def login_mobile(self, **kwargs):
        ensure_db()
        payload = _json_request_payload(kwargs)

        name = payload.get("name") or payload.get("login")
        password = payload.get("password")
        if not name or not password:
            return {"success": False, "errMsg": "请输入账号和密码"}

        try:
            auth_info = request.session.authenticate(
                request.db,
                {"login": name, "password": password, "type": "password"},
            )
        except AccessDenied:
            return {"success": False, "errMsg": "账号或密码错误"}
        except Exception as exc:
            return {"success": False, "errMsg": _error_message(exc)}

        uid = auth_info.get("uid")
        if uid and uid == request.session.uid:
            request.session.db = request.db
            return {"success": True, "errMsg": "登录成功！", "uid": uid}
        if uid:
            return {"success": False, "errMsg": "该账号需要额外验证，请使用网页端登录"}
        return {"success": False, "errMsg": "账号或密码错误"}
