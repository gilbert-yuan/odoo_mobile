# -*- coding: utf-8 -*-
import ast
import base64
import copy
import datetime
import json
import mimetypes
import os

import jinja2

from odoo import api, fields, http, models
from odoo.addons.web.controllers.utils import ensure_db
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.tools import json_default
from odoo.tools.float_utils import float_round
from odoo.tools.safe_eval import safe_eval


ISODATEFORMAT = "%Y-%m-%d"
ISODATETIMEFORMAT = "%Y-%m-%d %H:%M:%S"
MOBILEDATETIMEFORMAT = "%Y-%m-%d %H:%M"
SUPERUSER_ID = 1
HIDDEN_ONE2MANY_FIELD_TYPES = {"json", "properties", "serialized"}

STATIC_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), "static"))
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(STATIC_PATH),
    autoescape=True,
)


def _json_response(value):
    return request.make_response(
        json.dumps(value, ensure_ascii=False, default=json_default),
        headers=[("Content-Type", "application/json; charset=utf-8")],
    )


def _format_mobile_default_value(field_value, value):
    if value in (None, ""):
        return value
    if field_value.get("widget") == "float_time":
        return float_round(value, precision_digits=2)
    field_type = field_value.get("type")
    if field_type == "date":
        date_obj = fields.Date.to_date(value)
        return date_obj.strftime(ISODATEFORMAT) if date_obj else ""
    if field_type == "datetime":
        date_obj = fields.Datetime.to_datetime(value)
        return date_obj.strftime(MOBILEDATETIMEFORMAT) if date_obj else ""
    return value


def _json_request_payload(params):
    payload = dict(params or {})
    if payload:
        return payload
    try:
        raw_payload = request.get_json_data()
    except ValueError:
        return {}
    if not isinstance(raw_payload, dict):
        return {}
    nested_payload = raw_payload.get("params")
    return nested_payload if isinstance(nested_payload, dict) else raw_payload


def _literal(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (list, tuple, dict)):
        return value
    eval_context = {
        "uid": request.uid if request else False,
        "user": request.env.user if request and request.env else False,
        "context": dict(request.env.context) if request and request.env else {},
    }
    try:
        return safe_eval(value, eval_context)
    except Exception:
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return default


def _error_message(exc):
    if hasattr(exc, "diag") and getattr(exc.diag, "message_primary", None):
        return exc.diag.message_primary
    message = str(exc)
    return message if message and message != "None" else exc.__class__.__name__


def _split_names(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _or_domain(field_names, operator, value):
    names = _split_names(field_names)
    if not names or not value:
        return []
    return ["|"] * (len(names) - 1) + [(name, operator, value) for name in names]


def _name_get(records):
    return [(record.id, record.display_name) for record in records]


def _is_visible_one2many_field(field):
    field_type = field.get("type") if isinstance(field, dict) else field.field_type
    return field_type not in HIDDEN_ONE2MANY_FIELD_TYPES


class MobileGridLabel(models.Model):
    _name = "mobile.grid.label"
    _description = "Mobile Grid Label"

    name = fields.Char("名称")
    sequence = fields.Integer("顺序")


class MobileAction(models.Model):
    _name = "mobile.action"
    _description = "Mobile Action"
    _rec_name = "mobile_grid_id"

    def _compute_mobile_view_id(self):
        for action in self:
            view = self.env["mobile.view"].search([("mobile_action_id", "=", action.id)], limit=1)
            action.mobile_view_id = view.id

    model_id = fields.Many2one("ir.model", "模型名称")
    name = fields.Char("名称")
    limit = fields.Integer("limit")
    offset = fields.Integer("offset")
    order = fields.Char("order")
    context = fields.Char("context")
    mobile_grid_id = fields.Many2one("mobile.grid", "Grid ID")
    mobile_view_id = fields.Many2one("mobile.view", compute="_compute_mobile_view_id", string="Grid ID")

    _sql_constraints = [
        ("model_mobile_grid_id_field_id_uniq", "unique (mobile_grid_id)", "一个菜单只能对应一个动作"),
    ]


class MobileView(models.Model):
    _name = "mobile.view"
    _description = "Mobile View"
    _rec_name = "mobile_action_id"

    mobile_action_id = fields.Many2one("mobile.action", "动作")
    mobile_field_ids = fields.One2many("mobile.field", "view_id", string="视图表", copy=True)
    no_form = fields.Boolean("不显示form", default=True)
    model_id = fields.Many2one("ir.model", "模型名称", copy=True)
    domain_ids = fields.One2many("mobile.domain", "view_id", string="domain", copy=True)
    view_type = fields.Selection(
        [
            ("tree", "列表视图"),
            ("card", "看板"),
            ("view_form", "表单"),
            ("edit_form", "编辑表单"),
        ],
        "view type",
        copy=True,
    )
    button_ids = fields.One2many("mobile.button", "view_id", string="buttons", copy=True)
    show_form_view = fields.Many2one("mobile.view", "展示表单", copy=True)
    context = fields.Text("附加值")
    field_layout = fields.Selection(
        [
            ("auto", "自动"),
            ("accordion", "折叠分组"),
            ("tabs", "标签页"),
            ("plain", "平铺"),
        ],
        string="字段显示方式",
        default="auto",
        copy=True,
    )
    field_auto_limit = fields.Integer("未分组首屏字段数", default=8, copy=True)
    button_limit = fields.Integer("首屏按钮数", default=3, copy=True)
    button_collapse = fields.Boolean("按钮过多自动折叠", default=True, copy=True)

    _sql_constraints = [
        ("model_mobile_action_id_field_id_uniq", "unique (mobile_action_id)", "一个动作只能对应一个主视图"),
    ]


class One2ManyField(models.Model):
    _name = "one.many.field"
    _description = "One2Many Field"

    mobile_field_ids = fields.Many2many("mobile.field", "one_many_field_mobile_field_rel", string="视图表")


class MobileDomain(models.Model):
    _name = "mobile.domain"
    _description = "Mobile Domain"
    _order = "sequence"

    view_id = fields.Many2one("mobile.view", string="view", copy=True)
    domain = fields.Char("domain", copy=True)
    sequence = fields.Integer("顺序", copy=True)
    name = fields.Char("名称", copy=True)


class MobileButton(models.Model):
    _name = "mobile.button"
    _description = "Mobile Button"
    _order = "sequence, id"

    sequence = fields.Integer("顺序", default=10, copy=True)
    name = fields.Char("名称", copy=True)
    button_method = fields.Char("方法名", copy=True)
    button_group = fields.Char("按钮分组", copy=True)
    button_style = fields.Selection(
        [
            ("auto", "自动"),
            ("primary", "主按钮"),
            ("secondary", "普通按钮"),
            ("danger", "危险按钮"),
            ("text", "文字按钮"),
        ],
        string="按钮样式",
        default="auto",
        copy=True,
    )
    button_icon = fields.Char("图标", copy=True, help="可配置简短文字或图标字符，例如 ✓、↻、!")
    button_folded = fields.Boolean("默认放入更多", copy=True)
    button_confirm = fields.Char("确认提示", copy=True)
    show_condition = fields.Char("显示前提", copy=True, default="[]")
    view_id = fields.Many2one("mobile.view", string="视图", copy=True)
    group_ids = fields.Many2many("res.groups", "button_groups_rel", "button_id", "group_id", string="用户组")


class MobileField(models.Model):
    _name = "mobile.field"
    _description = "Mobile Field"
    _order = "sequence"

    @api.model
    def _get_field_types(self):
        return sorted((key, key) for key in fields.MetaField.by_type)

    sequence = fields.Integer("序列")
    view_id = fields.Many2one("mobile.view", "视图ID", copy=True)
    ir_field = fields.Many2one("ir.model.fields", "字段", copy=True)
    domain = fields.Char("domain")
    widget = fields.Selection(
        [
            ("auto", "自动"),
            ("text", "单行文本"),
            ("textarea", "多行文本"),
            ("html", "HTML"),
            ("email", "邮箱"),
            ("phone", "电话"),
            ("url", "网址"),
            ("password", "密码"),
            ("copy", "可复制文本"),
            ("badge", "标签"),
            ("code", "代码"),
            ("date", "日期"),
            ("datetime", "日期时间"),
            ("time", "时间"),
            ("month", "月份"),
            ("week", "周"),
            ("float_time", "浮点时间"),
            ("slider", "滑块"),
            ("stepper", "步进器"),
            ("progressbar", "进度条"),
            ("percentage", "百分比"),
            ("attachment", "附件"),
            ("image", "图片"),
            ("dropdown", "下拉选择"),
            ("radio", "单选"),
            ("json", "JSON"),
            ("domain", "Domain"),
            ("reference", "引用"),
        ],
        string="移动端组件",
        default="auto",
        copy=True,
    )
    field_type = fields.Selection(selection="_get_field_types", related="ir_field.ttype", string="字段类型", readonly=True, copy=True)
    field_relation = fields.Char(related="ir_field.relation", string="字段关联", readonly=True, copy=True)
    field_selection = fields.Char(related="ir_field.selection", string="选择项目", readonly=True, copy=True)
    model_id = fields.Many2one("ir.model", string="类型", copy=True)
    required = fields.Boolean("必输", copy=True)
    readonly = fields.Boolean("只读", copy=True)
    invisible = fields.Boolean("不可见", copy=True)
    group_name = fields.Char("字段分组", copy=True)
    group_collapsed = fields.Boolean("默认折叠", copy=True)
    placeholder = fields.Char("占位提示", copy=True)
    relation_limit = fields.Integer("关联搜索条数", default=20, copy=True)
    relation_search_fields = fields.Char("关联搜索字段", copy=True, help="多个字段用英文逗号分隔，例如 name,default_code")
    allow_quick_create = fields.Boolean("允许快速创建", copy=True)
    binary_filename_field = fields.Char("文件名字段", copy=True, help="例如 datas_fname、file_name；留空则只保存二进制内容")
    binary_accept = fields.Char("允许文件类型", copy=True, help="例如 image/*、.pdf,.doc,.docx")
    binary_max_size_mb = fields.Integer("最大文件MB", default=8, copy=True)
    image_max_width = fields.Integer("图片最大边长", default=1600, copy=True)
    image_quality = fields.Float("图片压缩质量", default=0.86, copy=True)
    selection_searchable = fields.Boolean("下拉可搜索", default=True, copy=True)
    number_min = fields.Float("最小值", copy=True)
    number_max = fields.Float("最大值", copy=True)
    number_step = fields.Float("步长", default=1, copy=True)
    field_id = fields.Many2one("mobile.field", "field_id", copy=True)
    many_field = fields.One2many("mobile.field", "field_id", string="one2many", copy=True)


class MobileGrid(models.Model):
    _name = "mobile.grid"
    _description = "Mobile Grid"
    _rec_name = "title"
    _order = "sequence"

    def _compute_mobile_action_id(self):
        for grid in self:
            action = self.env["mobile.action"].search([("mobile_grid_id", "=", grid.id)], limit=1)
            grid.mobile_action_id = action.id

    label_id = fields.Many2one("mobile.grid.label", "分类")
    sequence = fields.Integer(related="label_id.sequence", string="顺序", readonly=True)
    image = fields.Binary("图片")
    mobile_action_id = fields.Many2one("mobile.action", compute="_compute_mobile_action_id", string="动作")
    title = fields.Char("名称")


class MobileApiConfig(models.Model):
    _name = "mobile.api.config"
    _description = "Mobile API Config"
    _order = "sequence, id"

    name = fields.Char("名称", required=True)
    code = fields.Char("接口编码", required=True, index=True)
    sequence = fields.Integer("顺序", default=10)
    active = fields.Boolean("启用", default=True)
    auth_type = fields.Selection(
        [("user", "登录用户"), ("public", "公开")],
        string="认证方式",
        default="user",
        required=True,
    )
    operation = fields.Selection(
        [
            ("search_read", "查询列表"),
            ("read", "读取记录"),
            ("create", "创建"),
            ("write", "更新"),
            ("unlink", "删除"),
            ("method", "调用方法"),
        ],
        string="操作类型",
        default="search_read",
        required=True,
    )
    model_id = fields.Many2one("ir.model", "模型", required=True, ondelete="cascade")
    model = fields.Char(related="model_id.model", string="模型技术名", readonly=True, store=True)
    method_name = fields.Char("方法名")
    domain = fields.Text("默认域", default="[]")
    context = fields.Text("上下文", default="{}")
    field_names = fields.Char("字段列表", help="英文逗号分隔；留空时由 Odoo 默认字段决定。")
    order = fields.Char("排序")
    limit = fields.Integer("默认条数", default=80)
    use_sudo = fields.Boolean("使用 sudo", default=False)
    group_ids = fields.Many2many("res.groups", "mobile_api_config_group_rel", "api_id", "group_id", string="允许用户组")

    _sql_constraints = [
        ("mobile_api_config_code_uniq", "unique(code)", "接口编码必须唯一。"),
    ]

    def _check_access(self):
        self.ensure_one()
        if not self.active:
            return False
        if self.auth_type == "user" and not request.session.uid:
            return False
        if not self.group_ids:
            return True
        user_groups = request.env.user.groups_id
        return bool(self.group_ids & user_groups)

    def _model_env(self):
        self.ensure_one()
        model = request.env[self.model]
        return model.sudo() if self.use_sudo else model

    def _fields(self):
        self.ensure_one()
        return [field.strip() for field in (self.field_names or "").split(",") if field.strip()]

    def _api_context(self, payload):
        self.ensure_one()
        context = _literal(self.context, {})
        payload_context = payload.get("context") or {}
        if isinstance(payload_context, str):
            payload_context = _literal(payload_context, {})
        return dict(context, **payload_context)

    def _domain(self, payload):
        self.ensure_one()
        domain = _literal(self.domain, [])
        extra_domain = payload.get("domain") or []
        if isinstance(extra_domain, str):
            extra_domain = _literal(extra_domain, [])
        keyword = payload.get("keyword")
        keyword_fields = payload.get("keyword_fields") or ["display_name"]
        if keyword:
            keyword_domain = []
            for field_name in keyword_fields:
                if keyword_domain:
                    keyword_domain.insert(0, "|")
                keyword_domain.append((field_name, "ilike", keyword))
            extra_domain = list(extra_domain) + keyword_domain
        return list(domain) + list(extra_domain)

    def execute_mobile_api(self, payload):
        self.ensure_one()
        if not self._check_access():
            return {"success": False, "errMsg": "无权访问该接口"}

        payload = payload or {}
        model = self._model_env().with_context(**self._api_context(payload))
        fields_list = payload.get("fields") or self._fields()
        ids = payload.get("ids") or payload.get("id")
        if isinstance(ids, int):
            ids = [ids]
        limit = int(payload.get("limit") or self.limit or 80)
        offset = int(payload.get("offset") or 0)
        order = payload.get("order") or self.order or None

        if self.operation == "search_read":
            return model.search_read(self._domain(payload), fields=fields_list or None, offset=offset, limit=limit, order=order)
        if self.operation == "read":
            return model.browse(ids or []).read(fields_list or None)
        if self.operation == "create":
            record = model.create(payload.get("values") or {})
            return {"success": True, "id": record.id, "display_name": record.display_name}
        if self.operation == "write":
            records = model.browse(ids or [])
            records.write(payload.get("values") or {})
            return {"success": True, "ids": records.ids}
        if self.operation == "unlink":
            records = model.browse(ids or [])
            deleted_ids = records.ids
            records.unlink()
            return {"success": True, "ids": deleted_ids}
        if self.operation == "method":
            if not self.method_name or self.method_name.startswith("_"):
                return {"success": False, "errMsg": "未配置可调用方法"}
            records = model.browse(ids or [])
            target = records if records else model
            result = getattr(target, self.method_name)(**(payload.get("kwargs") or {}))
            return result if result is not None else {"success": True}
        return {"success": False, "errMsg": "不支持的接口操作"}


class MobileSampleGenerator(models.TransientModel):
    _name = "mobile.sample.generator"
    _description = "Mobile Official Module Sample Generator"

    include_sale = fields.Boolean("销售", default=True)
    include_purchase = fields.Boolean("采购", default=True)
    include_inventory = fields.Boolean("库存", default=True)
    include_account = fields.Boolean("发票/会计", default=True)
    include_crm = fields.Boolean("CRM", default=True)
    include_project = fields.Boolean("项目", default=True)
    include_mrp = fields.Boolean("制造", default=True)
    result = fields.Text("生成结果", readonly=True)

    def action_generate(self):
        self.ensure_one()
        samples = []
        if self.include_sale:
            samples.append(self._sale_sample())
        if self.include_purchase:
            samples.append(self._purchase_sample())
        if self.include_inventory:
            samples.append(self._inventory_sample())
        if self.include_account:
            samples.append(self._account_sample())
        if self.include_crm:
            samples.append(self._crm_sample())
        if self.include_project:
            samples.append(self._project_sample())
        if self.include_mrp:
            samples.append(self._mrp_sample())

        messages = [self._generate_sample(sample) for sample in samples]
        self.result = "\n".join(messages) or "没有选择任何示例。"
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _sample_label(self):
        return self.env["mobile.grid.label"].sudo().search([("name", "=", "官方模块示例")], limit=1) or self.env[
            "mobile.grid.label"
        ].sudo().create({"name": "官方模块示例", "sequence": 900})

    def _model(self, model_name):
        return self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)

    def _ir_field(self, model, field_name):
        return self.env["ir.model.fields"].sudo().search([("model_id", "=", model.id), ("name", "=", field_name)], limit=1)

    def _resolve_field(self, model, spec):
        for field_name in spec.get("candidates", [spec["name"]]):
            field = self._ir_field(model, field_name)
            if field:
                return field
        return self.env["ir.model.fields"]

    def _generate_sample(self, sample):
        model = self._model(sample["model"])
        if not model:
            return "跳过 %s：模型 %s 未安装。" % (sample["title"], sample["model"])

        label = self._sample_label()
        grid = self.env["mobile.grid"].sudo().search([("label_id", "=", label.id), ("title", "=", sample["title"])], limit=1)
        if not grid:
            grid = self.env["mobile.grid"].sudo().create({"label_id": label.id, "title": sample["title"]})

        action = self.env["mobile.action"].sudo().search([("mobile_grid_id", "=", grid.id)], limit=1)
        action_values = {
            "mobile_grid_id": grid.id,
            "model_id": model.id,
            "name": sample["title"],
            "limit": sample.get("limit", 20),
            "offset": sample.get("offset", 20),
            "order": sample.get("order", "id DESC"),
            "context": sample.get("context", "{}"),
        }
        if action:
            action.write(action_values)
        else:
            action = self.env["mobile.action"].sudo().create(action_values)

        main_view = self.env["mobile.view"].sudo().search([("mobile_action_id", "=", action.id)], limit=1)
        if not main_view:
            main_view = self.env["mobile.view"].sudo().create(
                {"mobile_action_id": action.id, "model_id": model.id, "view_type": "tree", "no_form": False}
            )

        form_view = main_view.show_form_view
        if not form_view:
            form_view = self.env["mobile.view"].sudo().create({"model_id": model.id, "view_type": "edit_form", "no_form": False})

        form_view.write(
            {
                "model_id": model.id,
                "view_type": "edit_form",
                "no_form": False,
                "context": sample.get("form_context", "{}"),
                "field_layout": sample.get("form_layout", "tabs"),
                "field_auto_limit": sample.get("field_auto_limit", 8),
                "button_limit": sample.get("button_limit", 3),
                "button_collapse": sample.get("button_collapse", True),
            }
        )
        main_view.write(
            {
                "model_id": model.id,
                "view_type": sample.get("view_type", "tree"),
                "no_form": False,
                "show_form_view": form_view.id,
                "context": sample.get("context", "{}"),
                "field_layout": sample.get("list_layout", "accordion"),
                "field_auto_limit": sample.get("field_auto_limit", 8),
                "button_limit": sample.get("button_limit", 3),
                "button_collapse": sample.get("button_collapse", True),
            }
        )

        self._clear_view(main_view)
        self._clear_view(form_view)
        list_count, list_missing = self._create_fields(main_view, model, sample.get("list_fields", []))
        form_count, form_missing = self._create_fields(form_view, model, sample.get("form_fields", []))
        self._create_domains(main_view, sample.get("domains", []))
        button_count = self._create_buttons(form_view, model.model, sample.get("buttons", []))

        missing = sorted(set(list_missing + form_missing))
        suffix = "；缺少字段：%s" % ", ".join(missing) if missing else ""
        return "生成 %s：列表字段 %s 个，表单字段 %s 个，按钮 %s 个%s。" % (sample["title"], list_count, form_count, button_count, suffix)

    def _clear_view(self, view):
        direct_fields = view.mobile_field_ids.sudo()
        if direct_fields:
            self.env["mobile.field"].sudo().search([("field_id", "in", direct_fields.ids)]).unlink()
            direct_fields.unlink()
        view.domain_ids.sudo().unlink()
        view.button_ids.sudo().unlink()

    def _create_domains(self, view, domains):
        for index, domain in enumerate(domains, start=1):
            self.env["mobile.domain"].sudo().create(
                {
                    "view_id": view.id,
                    "name": domain["name"],
                    "domain": domain.get("domain", "[]"),
                    "sequence": index,
                }
            )

    def _create_buttons(self, view, model_name, specs):
        created = 0
        model = self.env[model_name]
        for sequence, spec in enumerate(specs, start=1):
            method = spec.get("method")
            if not method or not hasattr(model, method):
                continue
            self.env["mobile.button"].sudo().create(
                {
                    "view_id": view.id,
                    "sequence": spec.get("sequence", sequence * 10),
                    "name": spec.get("name") or method,
                    "button_method": method,
                    "button_group": spec.get("group", "操作"),
                    "button_style": spec.get("style", "auto"),
                    "button_icon": spec.get("icon", ""),
                    "button_folded": spec.get("folded", False),
                    "button_confirm": spec.get("confirm", ""),
                    "show_condition": spec.get("show_condition", "[]"),
                }
            )
            created += 1
        return created

    def _create_fields(self, view, model, specs):
        created = 0
        missing = []
        for sequence, spec in enumerate(specs, start=1):
            field = self._resolve_field(model, spec)
            if not field:
                missing.append("%s.%s" % (model.model, "/".join(spec.get("candidates", [spec["name"]]))))
                continue
            parent = self._create_mobile_field(view, model, field, spec, sequence)
            created += 1
            if spec.get("children"):
                child_model = self._model(field.relation)
                if not child_model:
                    missing.append(field.relation or "%s.%s.relation" % (model.model, spec["name"]))
                    continue
                for child_sequence, child_spec in enumerate(spec["children"], start=1):
                    child_field = self._resolve_field(child_model, child_spec)
                    if not child_field:
                        missing.append("%s.%s" % (child_model.model, "/".join(child_spec.get("candidates", [child_spec["name"]]))))
                        continue
                    self._create_mobile_field(view, child_model, child_field, child_spec, child_sequence, parent)
        return created, missing

    def _create_mobile_field(self, view, model, field, spec, sequence, parent=None):
        values = {
            "sequence": sequence * 10,
            "model_id": model.id,
            "ir_field": field.id,
            "field_id": parent.id if parent else False,
            "view_id": False if parent else view.id,
            "widget": spec.get("widget", "auto"),
            "required": spec.get("required", False),
            "readonly": spec.get("readonly", False),
            "invisible": spec.get("invisible", False),
            "group_name": spec.get("group", ""),
            "group_collapsed": spec.get("group_collapsed", False),
            "domain": spec.get("domain", "[]"),
            "placeholder": spec.get("placeholder", ""),
            "relation_limit": spec.get("relation_limit", 20),
            "relation_search_fields": spec.get("relation_search_fields", ""),
            "allow_quick_create": spec.get("allow_quick_create", False),
            "binary_filename_field": spec.get("filename_field", ""),
            "binary_accept": spec.get("accept", ""),
            "binary_max_size_mb": spec.get("max_size_mb", 8),
            "image_max_width": spec.get("image_max_width", 1600),
            "image_quality": spec.get("image_quality", 0.86),
            "selection_searchable": spec.get("searchable", True),
            "number_min": spec.get("min", 0),
            "number_max": spec.get("max", 0),
            "number_step": spec.get("step", 1),
        }
        return self.env["mobile.field"].sudo().create(values)

    def _f(self, name, **kwargs):
        data = {"name": name}
        data.update(kwargs)
        return data

    def _fc(self, *names, **kwargs):
        data = {"name": names[0], "candidates": list(names)}
        data.update(kwargs)
        return data

    def _b(self, name, method, **kwargs):
        data = {"name": name, "method": method}
        data.update(kwargs)
        return data

    def _sale_sample(self):
        return {
            "title": "销售订单复杂示例",
            "model": "sale.order",
            "order": "date_order DESC",
            "domains": [
                {"name": "全部", "domain": "[]"},
                {"name": "报价中", "domain": "[('state', 'in', ['draft', 'sent'])]"},
                {"name": "已确认", "domain": "[('state', '=', 'sale')]"},
            ],
            "buttons": [
                self._b("确认订单", "action_confirm", style="primary", group="流程", show_condition="[('state', 'in', ['draft', 'sent'])]"),
                self._b("发送报价", "action_quotation_send", group="流程", folded=True, show_condition="[('state', 'in', ['draft', 'sent'])]"),
                self._b("取消订单", "action_cancel", style="danger", group="更多", folded=True, confirm="确认取消这张销售订单？", show_condition="[('state', 'not in', ['cancel'])]"),
            ],
            "list_fields": [
                self._f("name", widget="copy"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("date_order", widget="datetime"),
                self._f("user_id"),
                self._f("team_id"),
                self._f("amount_total", readonly=True),
                self._f("state", widget="dropdown"),
            ],
            "form_fields": [
                self._f("name", widget="copy", readonly=True),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("date_order", widget="datetime"),
                self._f("validity_date", widget="date"),
                self._f("pricelist_id"),
                self._f("payment_term_id"),
                self._f("user_id"),
                self._f("team_id"),
                self._f("state", widget="dropdown", readonly=True),
                self._f("amount_untaxed", readonly=True),
                self._f("amount_total", readonly=True),
                self._f("note", widget="html"),
                self._f(
                    "order_line",
                    children=[
                        self._f("product_id", relation_search_fields="name,default_code,barcode"),
                        self._f("name", widget="textarea"),
                        self._f("product_uom_qty", widget="stepper", min=0, step=1),
                        self._f("product_uom"),
                        self._f("price_unit", step=0.01),
                        self._f("discount", widget="percentage", min=0, max=100, step=1),
                        self._f("tax_id"),
                        self._f("price_subtotal", readonly=True),
                    ],
                ),
            ],
        }

    def _purchase_sample(self):
        return {
            "title": "采购订单复杂示例",
            "model": "purchase.order",
            "order": "date_order DESC",
            "domains": [
                {"name": "全部", "domain": "[]"},
                {"name": "询价中", "domain": "[('state', 'in', ['draft', 'sent', 'to approve'])]"},
                {"name": "已采购", "domain": "[('state', '=', 'purchase')]"},
            ],
            "buttons": [
                self._b("确认采购", "button_confirm", style="primary", group="流程", show_condition="[('state', 'in', ['draft', 'sent', 'to approve'])]"),
                self._b("发送询价", "action_rfq_send", group="流程", folded=True, show_condition="[('state', 'in', ['draft', 'sent'])]"),
                self._b("取消采购", "button_cancel", style="danger", group="更多", folded=True, confirm="确认取消这张采购订单？", show_condition="[('state', 'not in', ['cancel'])]"),
            ],
            "list_fields": [
                self._f("name", widget="copy"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("date_order", widget="datetime"),
                self._f("user_id"),
                self._f("amount_total", readonly=True),
                self._f("state", widget="dropdown"),
            ],
            "form_fields": [
                self._f("name", widget="copy", readonly=True),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("date_order", widget="datetime"),
                self._f("date_planned", widget="datetime"),
                self._f("user_id"),
                self._f("currency_id", readonly=True),
                self._f("payment_term_id"),
                self._f("fiscal_position_id"),
                self._f("state", widget="dropdown", readonly=True),
                self._f("amount_total", readonly=True),
                self._f("notes", widget="html"),
                self._f(
                    "order_line",
                    children=[
                        self._f("product_id", relation_search_fields="name,default_code,barcode"),
                        self._f("name", widget="textarea"),
                        self._f("product_qty", widget="stepper", min=0, step=1),
                        self._f("product_uom"),
                        self._f("price_unit", step=0.01),
                        self._f("taxes_id"),
                        self._f("price_subtotal", readonly=True),
                    ],
                ),
            ],
        }

    def _inventory_sample(self):
        return {
            "title": "库存调拨复杂示例",
            "model": "stock.picking",
            "order": "scheduled_date DESC",
            "domains": [
                {"name": "全部", "domain": "[]"},
                {"name": "待处理", "domain": "[('state', 'in', ['confirmed', 'waiting', 'assigned'])]"},
                {"name": "已完成", "domain": "[('state', '=', 'done')]"},
            ],
            "buttons": [
                self._b("检查可用量", "action_assign", style="primary", group="流程", show_condition="[('state', 'in', ['confirmed', 'waiting'])]"),
                self._b("验证", "button_validate", style="primary", group="流程", show_condition="[('state', 'in', ['assigned'])]"),
                self._b("取消调拨", "action_cancel", style="danger", group="更多", folded=True, confirm="确认取消这张调拨单？", show_condition="[('state', 'not in', ['done', 'cancel'])]"),
            ],
            "list_fields": [
                self._f("name", widget="copy"),
                self._f("picking_type_id"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("scheduled_date", widget="datetime"),
                self._f("origin", widget="copy"),
                self._f("state", widget="dropdown"),
            ],
            "form_fields": [
                self._f("name", widget="copy", readonly=True),
                self._f("picking_type_id"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("scheduled_date", widget="datetime"),
                self._f("origin", widget="copy"),
                self._f("location_id"),
                self._f("location_dest_id"),
                self._f("state", widget="dropdown", readonly=True),
                self._f(
                    "move_ids_without_package",
                    children=[
                        self._f("product_id", relation_search_fields="name,default_code,barcode"),
                        self._f("product_uom_qty", widget="stepper", min=0, step=1),
                        self._fc("quantity", "quantity_done", widget="stepper", min=0, step=1),
                        self._f("product_uom"),
                        self._f("location_id"),
                        self._f("location_dest_id"),
                        self._f("state", widget="dropdown", readonly=True),
                    ],
                ),
            ],
        }

    def _account_sample(self):
        return {
            "title": "客户发票复杂示例",
            "model": "account.move",
            "order": "invoice_date DESC, id DESC",
            "domains": [
                {"name": "客户发票", "domain": "[('move_type', 'in', ['out_invoice', 'out_refund'])]"},
                {"name": "供应商账单", "domain": "[('move_type', 'in', ['in_invoice', 'in_refund'])]"},
                {"name": "未付款", "domain": "[('payment_state', 'not in', ['paid', 'reversed'])]"},
            ],
            "buttons": [
                self._b("过账", "action_post", style="primary", group="流程", show_condition="[('state', '=', 'draft')]"),
                self._b("预览", "preview_invoice", group="流程", folded=True),
                self._b("重置为草稿", "button_draft", group="更多", folded=True, show_condition="[('state', '=', 'cancel')]"),
            ],
            "list_fields": [
                self._f("name", widget="copy"),
                self._f("move_type", widget="dropdown"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("invoice_date", widget="date"),
                self._f("invoice_date_due", widget="date"),
                self._f("amount_total", readonly=True),
                self._f("payment_state", widget="dropdown", readonly=True),
                self._f("state", widget="dropdown", readonly=True),
            ],
            "form_fields": [
                self._f("name", widget="copy", readonly=True),
                self._f("move_type", widget="dropdown"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("invoice_date", widget="date"),
                self._f("invoice_date_due", widget="date"),
                self._f("invoice_payment_term_id"),
                self._f("currency_id", readonly=True),
                self._f("ref", widget="copy"),
                self._f("amount_total", readonly=True),
                self._f("payment_state", widget="dropdown", readonly=True),
                self._f("narration", widget="html"),
                self._f(
                    "invoice_line_ids",
                    children=[
                        self._f("product_id", relation_search_fields="name,default_code,barcode"),
                        self._f("name", widget="textarea"),
                        self._f("quantity", widget="stepper", min=0, step=1),
                        self._f("price_unit", step=0.01),
                        self._f("discount", widget="percentage", min=0, max=100, step=1),
                        self._f("tax_ids"),
                        self._f("price_subtotal", readonly=True),
                    ],
                ),
            ],
        }

    def _crm_sample(self):
        return {
            "title": "CRM线索复杂示例",
            "model": "crm.lead",
            "order": "create_date DESC",
            "domains": [
                {"name": "全部", "domain": "[]"},
                {"name": "我的机会", "domain": "[('user_id', '=', uid)]"},
                {"name": "未赢单", "domain": "[('probability', '<', 100)]"},
            ],
            "buttons": [
                self._b("标记赢单", "action_set_won_rainbowman", style="primary", group="流程", show_condition="[('probability', '<', 100)]"),
                self._b("转为报价", "action_sale_quotations_new", group="更多", folded=True),
            ],
            "list_fields": [
                self._f("name"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("email_from", widget="email"),
                self._f("phone", widget="phone"),
                self._f("expected_revenue", step=0.01),
                self._f("probability", widget="slider", min=0, max=100, step=1),
                self._f("stage_id"),
                self._f("user_id"),
            ],
            "form_fields": [
                self._f("name"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("contact_name"),
                self._f("email_from", widget="email"),
                self._f("phone", widget="phone"),
                self._f("mobile", widget="phone"),
                self._f("expected_revenue", step=0.01),
                self._f("probability", widget="slider", min=0, max=100, step=1),
                self._f("stage_id"),
                self._f("user_id"),
                self._f("team_id"),
                self._f("tag_ids"),
                self._f("date_deadline", widget="date"),
                self._f("description", widget="html"),
            ],
        }

    def _project_sample(self):
        return {
            "title": "项目任务复杂示例",
            "model": "project.task",
            "order": "date_deadline ASC, id DESC",
            "domains": [
                {"name": "全部", "domain": "[]"},
                {"name": "我的任务", "domain": "[('user_ids', 'in', [uid])]"},
                {"name": "有截止日期", "domain": "[('date_deadline', '!=', False)]"},
            ],
            "buttons": [
                self._b("标记完成", "action_fsm_validate", style="primary", group="流程", show_condition="[('stage_id.fold', '=', False)]"),
                self._b("删除任务", "unlink", style="danger", group="更多", folded=True, confirm="确认删除这个任务？"),
            ],
            "list_fields": [
                self._f("name"),
                self._f("project_id"),
                self._f("user_ids"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("date_deadline", widget="date"),
                self._f("stage_id"),
                self._f("priority", widget="dropdown"),
            ],
            "form_fields": [
                self._f("name"),
                self._f("project_id"),
                self._f("user_ids"),
                self._f("partner_id", relation_search_fields="name,email,phone"),
                self._f("date_deadline", widget="date"),
                self._f("priority", widget="dropdown"),
                self._f("stage_id"),
                self._f("tag_ids"),
                self._f("allocated_hours", widget="stepper", min=0, step=0.5),
                self._fc("progress", "effective_hours", widget="slider", min=0, max=100, step=1),
                self._f("description", widget="html"),
            ],
        }

    def _mrp_sample(self):
        return {
            "title": "制造订单复杂示例",
            "model": "mrp.production",
            "order": "date_start DESC",
            "domains": [
                {"name": "全部", "domain": "[]"},
                {"name": "进行中", "domain": "[('state', 'in', ['confirmed', 'progress', 'to_close'])]"},
                {"name": "已完成", "domain": "[('state', '=', 'done')]"},
            ],
            "buttons": [
                self._b("确认生产", "action_confirm", style="primary", group="流程", show_condition="[('state', '=', 'draft')]"),
                self._b("开始生产", "button_plan", group="流程", show_condition="[('state', 'in', ['confirmed'])]"),
                self._b("取消制造", "action_cancel", style="danger", group="更多", folded=True, confirm="确认取消这张制造订单？", show_condition="[('state', 'not in', ['done', 'cancel'])]"),
            ],
            "list_fields": [
                self._f("name", widget="copy"),
                self._f("product_id", relation_search_fields="name,default_code,barcode"),
                self._f("product_qty", widget="stepper", min=0, step=1),
                self._f("date_start", widget="datetime"),
                self._f("date_finished", widget="datetime"),
                self._f("state", widget="dropdown"),
            ],
            "form_fields": [
                self._f("name", widget="copy", readonly=True),
                self._f("product_id", relation_search_fields="name,default_code,barcode"),
                self._f("bom_id"),
                self._f("product_qty", widget="stepper", min=0, step=1),
                self._f("product_uom_id"),
                self._f("date_start", widget="datetime"),
                self._f("date_finished", widget="datetime"),
                self._f("origin", widget="copy"),
                self._f("user_id"),
                self._f("company_id", readonly=True),
                self._f("state", widget="dropdown", readonly=True),
                self._f(
                    "move_raw_ids",
                    children=[
                        self._f("product_id", relation_search_fields="name,default_code,barcode"),
                        self._f("product_uom_qty", widget="stepper", min=0, step=1),
                        self._fc("quantity", "quantity_done", widget="stepper", min=0, step=1),
                        self._f("product_uom"),
                        self._f("state", widget="dropdown", readonly=True),
                    ],
                ),
                self._f(
                    "move_finished_ids",
                    children=[
                        self._f("product_id", relation_search_fields="name,default_code,barcode"),
                        self._f("product_uom_qty", widget="stepper", min=0, step=1),
                        self._fc("quantity", "quantity_done", widget="stepper", min=0, step=1),
                        self._f("product_uom"),
                        self._f("state", widget="dropdown", readonly=True),
                    ],
                ),
            ],
        }


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
            rows.append({"title": record.display_name, "id": record.id, "meta": row_fields})
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
