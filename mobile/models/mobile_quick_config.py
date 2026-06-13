# -*- coding: utf-8 -*-

from odoo import api, fields, models


class MobileQuickConfigWizard(models.TransientModel):
    _name = "mobile.quick.config.wizard"
    _description = "Mobile Quick Config Wizard"

    name = fields.Char("菜单名称", required=True)
    model_id = fields.Many2one(
        "ir.model",
        string="业务模型",
        required=True,
        domain="[('transient', '=', False)]",
        ondelete="cascade",
    )
    label_id = fields.Many2one(
        "mobile.grid.label",
        string="分组",
        ondelete="cascade",
        default=lambda self: self._default_label(),
    )
    view_type = fields.Selection(
        [("tree", "列表"), ("card", "卡片")],
        string="主视图",
        default="tree",
        required=True,
    )
    with_form = fields.Boolean("自动生成详情页", default=True)
    include_buttons = fields.Boolean("自动生成常用按钮", default=True)
    include_delete_button = fields.Boolean("包含删除按钮", default=False)
    field_limit = fields.Integer("字段数量", default=10)
    result = fields.Text("结果", readonly=True)

    @api.model
    def _default_label(self):
        return self.env["mobile.grid.label"].sudo().search([("name", "=", "快速配置")], limit=1)

    @api.onchange("model_id")
    def _onchange_model_id(self):
        for rec in self:
            if rec.model_id and not rec.name:
                rec.name = rec.model_id.name

    def _ensure_label(self):
        label = self.label_id.sudo() if self.label_id else self._default_label()
        if label:
            return label
        return self.env["mobile.grid.label"].sudo().create({"name": "快速配置", "sequence": 950})

    def _ensure_grid(self, label, title):
        grid = self.env["mobile.grid"].sudo().search([("label_id", "=", label.id), ("title", "=", title)], limit=1)
        if grid:
            return grid
        return self.env["mobile.grid"].sudo().create({"label_id": label.id, "title": title})

    def _ensure_action(self, grid, title):
        action = self.env["mobile.action"].sudo().search([("mobile_grid_id", "=", grid.id)], limit=1)
        values = {
            "mobile_grid_id": grid.id,
            "model_id": self.model_id.id,
            "name": title,
            "limit": 20,
            "offset": 20,
            "order": "id DESC",
            "context": "{}",
        }
        if action:
            action.write(values)
            return action
        return self.env["mobile.action"].sudo().create(values)

    def _ensure_views(self, action):
        main_view = self.env["mobile.view"].sudo().search([("mobile_action_id", "=", action.id)], limit=1)
        if not main_view:
            main_view = self.env["mobile.view"].sudo().create(
                {
                    "mobile_action_id": action.id,
                    "model_id": self.model_id.id,
                    "view_type": self.view_type,
                    "no_form": not self.with_form,
                }
            )

        main_vals = {
            "model_id": self.model_id.id,
            "view_type": self.view_type,
            "no_form": not self.with_form,
            "field_layout": "accordion",
            "field_auto_limit": 8,
            "summary_limit": 3,
            "button_limit": 3,
            "button_collapse": True,
            "context": "{}",
        }
        form_view = main_view.show_form_view
        if self.with_form:
            if not form_view:
                form_view = self.env["mobile.view"].sudo().create(
                    {
                        "model_id": self.model_id.id,
                        "view_type": "edit_form",
                        "no_form": False,
                        "field_layout": "tabs",
                        "field_auto_limit": 8,
                        "summary_limit": 3,
                        "button_limit": 3,
                        "button_collapse": True,
                    }
                )
            else:
                form_view.write(
                    {
                        "model_id": self.model_id.id,
                        "view_type": "edit_form",
                        "no_form": False,
                        "field_layout": "tabs",
                        "field_auto_limit": 8,
                        "summary_limit": 3,
                        "button_limit": 3,
                        "button_collapse": True,
                    }
                )
            main_vals["show_form_view"] = form_view.id
        else:
            main_vals["show_form_view"] = False

        main_view.write(main_vals)
        return main_view, form_view

    def _clear_view(self, view):
        if not view:
            return
        direct_fields = view.mobile_field_ids.sudo()
        if direct_fields:
            self.env["mobile.field"].sudo().search([("field_id", "in", direct_fields.ids)]).unlink()
            direct_fields.unlink()
        view.domain_ids.sudo().unlink()
        view.button_ids.sudo().unlink()

    def _preferred_names(self):
        return {
            "name": 1,
            "display_name": 2,
            "state": 3,
            "partner_id": 4,
            "user_id": 5,
            "team_id": 6,
            "date": 7,
            "date_order": 8,
            "create_date": 9,
            "write_date": 10,
            "amount_total": 11,
            "amount_untaxed": 12,
            "amount_residual": 13,
            "invoice_date": 14,
            "scheduled_date": 15,
            "origin": 16,
            "company_id": 17,
        }

    def _field_type_rank(self):
        return {
            "char": 1,
            "selection": 2,
            "many2one": 3,
            "date": 4,
            "datetime": 5,
            "monetary": 6,
            "float": 7,
            "integer": 8,
            "boolean": 9,
            "text": 10,
        }

    def _quick_fields(self, include_text=True):
        self.ensure_one()
        excluded_names = {
            "id",
            "display_name",
            "__last_update",
            "create_uid",
            "create_date",
            "write_uid",
            "write_date",
            "message_ids",
            "message_follower_ids",
            "activity_ids",
            "activity_state",
            "activity_exception_decoration",
            "activity_exception_icon",
            "activity_date_deadline",
        }
        allowed_types = {"char", "selection", "many2one", "date", "datetime", "monetary", "float", "integer", "boolean"}
        if include_text:
            allowed_types.add("text")

        fields_model = self.env["ir.model.fields"].sudo().search(
            [
                ("model_id", "=", self.model_id.id),
                ("store", "=", True),
                ("name", "not in", list(excluded_names)),
                ("ttype", "in", list(allowed_types)),
            ]
        )
        preferred = self._preferred_names()
        type_rank = self._field_type_rank()

        def _sort_key(field):
            return (
                preferred.get(field.name, 999),
                type_rank.get(field.ttype, 99),
                field.field_description or field.name,
                field.id,
            )

        ordered = sorted(fields_model, key=_sort_key)
        return ordered

    def _default_widget(self, ir_field):
        if ir_field.ttype == "selection":
            return "dropdown"
        if ir_field.ttype == "datetime":
            return "datetime"
        if ir_field.ttype == "date":
            return "date"
        if ir_field.name in ("name", "origin"):
            return "copy"
        return "auto"

    def _build_mobile_field_values(self, view, ir_field, sequence, summary=False):
        return {
            "sequence": sequence * 10,
            "model_id": self.model_id.id,
            "ir_field": ir_field.id,
            "field_id": False,
            "view_id": view.id,
            "widget": self._default_widget(ir_field),
            "required": bool(ir_field.required),
            "readonly": bool(ir_field.readonly),
            "invisible": False,
            "group_name": "",
            "group_collapsed": False,
            "summary_visible": summary,
            "summary_priority": sequence * 10,
            "summary_style": "status" if ir_field.name == "state" else "auto",
            "domain": "[]",
            "placeholder": "",
            "relation_limit": 20,
            "relation_search_fields": "",
            "allow_quick_create": False,
            "binary_filename_field": "",
            "binary_accept": "",
            "binary_max_size_mb": 8,
            "image_max_width": 1600,
            "image_quality": 0.86,
            "selection_searchable": True,
            "number_min": False,
            "number_max": False,
            "number_step": 1,
        }

    def _apply_fields(self, main_view, form_view):
        fields_pool = self._quick_fields(include_text=True)
        if not fields_pool:
            return 0

        list_limit = max(4, min(self.field_limit or 10, 20))
        form_limit = max(list_limit, min((self.field_limit or 10) * 2, 36))
        list_fields = fields_pool[:list_limit]
        form_fields = fields_pool[:form_limit]

        self._clear_view(main_view)
        self._clear_view(form_view)

        created = 0
        for index, ir_field in enumerate(list_fields, start=1):
            values = self._build_mobile_field_values(main_view, ir_field, index, summary=index <= 3)
            self.env["mobile.field"].sudo().create(values)
            created += 1

        if form_view and self.with_form:
            for index, ir_field in enumerate(form_fields, start=1):
                values = self._build_mobile_field_values(form_view, ir_field, index, summary=False)
                self.env["mobile.field"].sudo().create(values)
                created += 1
        return created

    def _apply_domains(self, main_view):
        self.env["mobile.domain"].sudo().create(
            {
                "view_id": main_view.id,
                "name": "全部",
                "domain": "[]",
                "sequence": 10,
            }
        )
        return 1

    def _button_spec_candidates(self):
        return [
            {"method": "action_confirm", "name": "确认", "style": "primary", "group": "流程", "sequence": 10},
            {"method": "button_confirm", "name": "确认", "style": "primary", "group": "流程", "sequence": 10},
            {"method": "action_assign", "name": "检查可用量", "style": "primary", "group": "流程", "sequence": 20},
            {"method": "button_validate", "name": "验证", "style": "primary", "group": "流程", "sequence": 20},
            {"method": "action_post", "name": "过账", "style": "primary", "group": "流程", "sequence": 20},
            {"method": "action_set_won_rainbowman", "name": "标记赢单", "style": "primary", "group": "流程", "sequence": 20},
            {"method": "action_cancel", "name": "取消", "style": "danger", "group": "更多", "sequence": 90, "folded": True, "confirm": "确认执行取消操作？"},
            {"method": "button_cancel", "name": "取消", "style": "danger", "group": "更多", "sequence": 90, "folded": True, "confirm": "确认执行取消操作？"},
            {"method": "action_draft", "name": "重置草稿", "style": "secondary", "group": "更多", "sequence": 80, "folded": True},
            {"method": "button_draft", "name": "重置草稿", "style": "secondary", "group": "更多", "sequence": 80, "folded": True},
        ]

    def _apply_buttons(self, view):
        if not view or not self.include_buttons:
            return 0

        model = self.env[self.model_id.model]
        created = 0
        seen_names = set()
        for spec in self._button_spec_candidates():
            method = spec["method"]
            if not hasattr(model, method):
                continue
            if spec["name"] in seen_names:
                continue
            seen_names.add(spec["name"])
            self.env["mobile.button"].sudo().create(
                {
                    "view_id": view.id,
                    "sequence": spec.get("sequence", (created + 1) * 10),
                    "name": spec["name"],
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
            if created >= 3:
                break

        if self.include_delete_button:
            self.env["mobile.button"].sudo().create(
                {
                    "view_id": view.id,
                    "sequence": 999,
                    "name": "删除",
                    "button_method": "unlink",
                    "button_group": "更多",
                    "button_style": "danger",
                    "button_icon": "",
                    "button_folded": True,
                    "button_confirm": "确认删除这条记录？",
                    "show_condition": "[]",
                }
            )
            created += 1
        return created

    def action_generate(self):
        self.ensure_one()
        title = (self.name or self.model_id.name or self.model_id.model or "").strip()
        if not title:
            title = self.model_id.model

        label = self._ensure_label()
        grid = self._ensure_grid(label, title)
        action = self._ensure_action(grid, title)
        main_view, form_view = self._ensure_views(action)

        fields_created = self._apply_fields(main_view, form_view)
        domains_created = self._apply_domains(main_view)
        button_view = form_view if (self.with_form and form_view) else main_view
        buttons_created = self._apply_buttons(button_view)

        self.result = (
            "快速配置完成：%s\n"
            "模型：%s\n"
            "主视图：%s\n"
            "字段：%s\n"
            "筛选标签：%s\n"
            "按钮：%s"
        ) % (
            title,
            self.model_id.model,
            "列表" if self.view_type == "tree" else "卡片",
            fields_created,
            domains_created,
            buttons_created,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
