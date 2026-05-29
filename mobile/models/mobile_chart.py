# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import date_utils


class MobileChartConfig(models.Model):
    _name = "mobile.chart.config"
    _description = "Mobile Chart Config"
    _order = "sequence, id"

    @api.model
    def _supported_model_domain(self):
        return [("model", "in", ["sale.order", "sale.report"])]

    @api.depends("model_id", "date_field_id")
    def _compute_date_field_name(self):
        for rec in self:
            rec.date_field_name = rec.date_field_id.name if rec.date_field_id and rec.date_field_id.model_id == rec.model_id else False

    @api.depends("model_id", "person_field_id")
    def _compute_person_field_name(self):
        for rec in self:
            rec.person_field_name = rec.person_field_id.name if rec.person_field_id and rec.person_field_id.model_id == rec.model_id else False

    @api.depends("model_id", "measure_field_id")
    def _compute_measure_field_name(self):
        for rec in self:
            rec.measure_field_name = rec.measure_field_id.name if rec.measure_field_id and rec.measure_field_id.model_id == rec.model_id else False

    sequence = fields.Integer("顺序", default=10)
    active = fields.Boolean("启用", default=True)
    name = fields.Char("名称", required=True)
    chart_code = fields.Char("图表编码", required=True, index=True, help="用于前端唯一识别")
    chart_type = fields.Selection(
        [("line", "折线图"), ("bar", "柱状图"), ("area", "面积图")],
        string="图表类型",
        default="line",
        required=True,
    )
    model_id = fields.Many2one(
        "ir.model",
        string="统计模型",
        required=True,
        ondelete="cascade",
        domain=lambda self: self._supported_model_domain(),
    )
    model_name = fields.Char(related="model_id.model", string="模型技术名", readonly=True, store=True)
    date_field_id = fields.Many2one(
        "ir.model.fields",
        string="时间字段",
        required=True,
        ondelete="cascade",
        domain="[('model_id', '=', model_id)]",
    )
    date_field_name = fields.Char(string="时间字段名", compute="_compute_date_field_name", store=True)
    person_field_id = fields.Many2one(
        "ir.model.fields",
        string="人员字段",
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('ttype', '=', 'many2one'), ('relation', '=', 'res.users')]",
    )
    person_field_name = fields.Char(string="人员字段名", compute="_compute_person_field_name", store=True)
    group_by = fields.Selection(
        [("month", "按月"), ("week", "按周"), ("day", "按天"), ("person", "按人员")],
        string="分组方式",
        default="month",
        required=True,
    )
    measure_type = fields.Selection(
        [("count", "记录数"), ("sum", "求和"), ("avg", "平均值")],
        string="指标方式",
        default="sum",
        required=True,
    )
    measure_field_id = fields.Many2one(
        "ir.model.fields",
        string="指标字段",
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['integer', 'float', 'monetary'])]",
    )
    measure_field_name = fields.Char(string="指标字段名", compute="_compute_measure_field_name", store=True)
    base_domain = fields.Text("基础过滤域", default="[]")
    state_field = fields.Char("状态字段", default="state", help="例如 state")
    done_states = fields.Char("完成状态值", default="sale,done", help="逗号分隔，例如 sale,done")
    y_axis_name = fields.Char("Y轴名称", default="数值")
    description = fields.Char("说明")

    _sql_constraints = [
        ("mobile_chart_config_code_uniq", "unique(chart_code)", "图表编码必须唯一。"),
    ]

    @api.onchange("model_id")
    def _onchange_model_id(self):
        for rec in self:
            if not rec.model_id:
                rec.date_field_id = False
                rec.person_field_id = False
                rec.measure_field_id = False
                continue
            if rec.date_field_id and rec.date_field_id.model_id != rec.model_id:
                rec.date_field_id = False
            if rec.person_field_id and rec.person_field_id.model_id != rec.model_id:
                rec.person_field_id = False
            if rec.measure_field_id and rec.measure_field_id.model_id != rec.model_id:
                rec.measure_field_id = False

    @api.constrains("group_by", "person_field_id")
    def _check_person_group(self):
        for rec in self:
            if rec.group_by == "person" and not rec.person_field_id:
                raise ValidationError("按人员分组必须配置人员字段。")
            if rec.person_field_id and rec.person_field_id.relation != "res.users":
                raise ValidationError("人员字段必须关联到 res.users。")
            if rec.group_by != "person" and not rec.person_field_id:
                continue

    @api.constrains("measure_type", "measure_field_id")
    def _check_measure_field(self):
        for rec in self:
            if rec.measure_type in ("sum", "avg") and not rec.measure_field_id:
                raise ValidationError("求和或平均值必须配置指标字段。")
            if rec.measure_field_id and rec.measure_field_id.ttype not in ("integer", "float", "monetary"):
                raise ValidationError("指标字段必须是数字类型。")

    @api.constrains("date_field_id")
    def _check_date_field(self):
        for rec in self:
            if rec.date_field_id and rec.date_field_id.ttype not in ("date", "datetime"):
                raise ValidationError("时间字段必须是日期或日期时间类型。")

    @api.constrains("chart_code")
    def _check_chart_code(self):
        for rec in self:
            code = (rec.chart_code or "").strip()
            if not code:
                raise ValidationError("图表编码不能为空。")
            if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in code):
                raise ValidationError("图表编码仅支持字母、数字、下划线和中划线。")

    def chart_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "code": self.chart_code,
            "title": self.name,
            "type": self.chart_type,
            "groupBy": self.group_by,
            "measureType": self.measure_type,
            "yAxisName": self.y_axis_name or "数值",
            "description": self.description or "",
        }


class MobileSampleGeneratorChartMixin(models.TransientModel):
    _inherit = "mobile.sample.generator"

    def action_generate(self):
        action = super().action_generate()
        if self.include_sale and self.include_sale_chart_data:
            message = self._ensure_sale_chart_sample_data()
            if message:
                self.result = ("%s\n%s" % (self.result or "", message)).strip()
        return action

    def action_clear(self):
        action = super().action_clear()
        messages = [self._clear_sale_chart_configs(), self._clear_sale_chart_sample_data()]
        extra = "\n".join([message for message in messages if message])
        if extra:
            self.result = ("%s\n%s" % (self.result or "", extra)).strip()
        return action

    def _ensure_chart(self, values):
        chart = self.env["mobile.chart.config"].sudo().search([("chart_code", "=", values["chart_code"])], limit=1)
        if chart:
            chart.write(values)
            return chart
        return self.env["mobile.chart.config"].sudo().create(values)

    def _chart_sample_tag(self):
        return "MOBILE_CHART_SAMPLE"

    def _clear_sale_chart_configs(self):
        configs = self.env["mobile.chart.config"].sudo().search([("chart_code", "in", ["sale_growth", "sale_amount", "sale_by_user"])])
        count = len(configs)
        if configs:
            configs.unlink()
        return "清除 销售图表配置：%s 条。" % count

    def _clear_sale_chart_sample_data(self):
        if not self._model("sale.order"):
            return "跳过 图表示例数据清理：模型 sale.order 未安装。"

        marker = self._chart_sample_tag()
        orders = self.env["sale.order"].sudo().search([("client_order_ref", "=like", "%s-%%" % marker)])
        if not orders:
            return "清除 图表示例数据：0 条。"

        to_cancel = orders.filtered(lambda order: order.state not in ("draft", "cancel"))
        if to_cancel:
            to_cancel.action_cancel()

        deletable = orders.filtered(lambda order: order.state in ("draft", "cancel"))
        deleted_count = len(deletable)
        if deletable:
            deletable.unlink()
        skipped_count = len(orders) - deleted_count
        if skipped_count:
            return "清除 图表示例数据：已删除 %s 条，跳过 %s 条（状态不可删除）。" % (deleted_count, skipped_count)
        return "清除 图表示例数据：%s 条。" % deleted_count

    def _chart_sample_partner(self):
        partner = self.env["res.partner"].sudo().search([("name", "=", "移动端图表示例客户")], limit=1)
        if partner:
            return partner
        return self.env["res.partner"].sudo().create(
            {
                "name": "移动端图表示例客户",
                "company_type": "company",
            }
        )

    def _chart_sample_product(self):
        template = self.env["product.template"].sudo().search([("name", "=", "移动端图表示例产品"), ("type", "=", "service")], limit=1)
        if template:
            return template.product_variant_id
        template = self.env["product.template"].sudo().create(
            {
                "name": "移动端图表示例产品",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
                "list_price": 1999.0,
            }
        )
        return template.product_variant_id

    def _chart_sample_users(self):
        users = self.env["res.users"].sudo().search(
            [("active", "=", True), ("share", "=", False), ("company_ids", "in", [self.env.company.id])],
            order="id",
            limit=3,
        )
        return users or self.env.user.sudo()

    def _build_sale_chart_sample_payload(self, user, product_id, partner_id, step, slot):
        base = 1600 + (step * 320) + (slot * 120) + ((user.id % 7) * 85)
        quantity = 1 + (slot % 2)
        price_unit = round(base / quantity, 2)
        order_line = [(0, 0, {"product_id": product_id, "product_uom_qty": quantity, "price_unit": price_unit})]
        return {
            "partner_id": partner_id,
            "user_id": user.id,
            "company_id": self.env.company.id,
            "state": "sale",
            "order_line": order_line,
        }

    def _ensure_sale_chart_sample_data(self):
        if not self._model("sale.order"):
            return "跳过 图表示例数据：模型 sale.order 未安装。"
        if not self._model("product.template"):
            return "跳过 图表示例数据：模型 product.template 未安装。"

        users = self._chart_sample_users()
        if not users:
            return "跳过 图表示例数据：没有可用业务员。"

        partner = self._chart_sample_partner()
        product = self._chart_sample_product()
        marker = self._chart_sample_tag()
        sale_order_model = self.env["sale.order"].sudo()

        created = 0
        existed = 0
        months = 6
        for step in range(months):
            month_offset = (months - 1) - step
            month_start = date_utils.start_of(fields.Datetime.subtract(fields.Datetime.now(), months=month_offset), "month")
            month_orders = 1 + (step // 2)
            for user in users:
                for slot in range(month_orders):
                    ref = "%s-%s-U%s-%s" % (marker, month_start.strftime("%Y%m"), user.id, slot + 1)
                    order = sale_order_model.search([("client_order_ref", "=", ref), ("company_id", "=", self.env.company.id)], limit=1)
                    if order:
                        existed += 1
                        continue

                    order_date = month_start + timedelta(days=min(27, 2 + (slot * 6) + (user.id % 3)), hours=9 + slot)
                    values = self._build_sale_chart_sample_payload(user, product.id, partner.id, step, slot)
                    values.update(
                        {
                            "client_order_ref": ref,
                            "date_order": fields.Datetime.to_string(order_date),
                        }
                    )
                    sale_order_model.create(values)
                    created += 1

        total = created + existed
        return "生成 图表示例数据：新增 %s 条，已存在 %s 条，总计 %s 条（近 %s 个月）。" % (created, existed, total, months)

    def _ensure_sale_chart_configs(self):
        model = self._model("sale.order")
        if not model:
            return "跳过 销售图表：模型 sale.order 未安装。"
        date_field = self._resolve_field(model, {"name": "date_order", "candidates": ["date_order", "create_date"]})
        person_field = self._resolve_field(model, {"name": "user_id", "candidates": ["user_id"]})
        amount_field = self._resolve_field(model, {"name": "amount_total", "candidates": ["amount_total"]})
        if not (date_field and person_field and amount_field):
            return "跳过 销售图表：缺少核心字段。"

        common = {
            "active": True,
            "model_id": model.id,
            "date_field_id": date_field.id,
            "person_field_id": person_field.id,
            "base_domain": "[]",
            "state_field": "state",
            "done_states": "sale,done",
        }
        self._ensure_chart(
            {
                **common,
                "sequence": 10,
                "name": "销售增长趋势",
                "chart_code": "sale_growth",
                "chart_type": "line",
                "group_by": "month",
                "measure_type": "count",
                "measure_field_id": False,
                "y_axis_name": "订单数",
                "description": "按月统计销售订单数量增长",
            }
        )
        self._ensure_chart(
            {
                **common,
                "sequence": 20,
                "name": "销售金额趋势",
                "chart_code": "sale_amount",
                "chart_type": "bar",
                "group_by": "month",
                "measure_type": "sum",
                "measure_field_id": amount_field.id,
                "y_axis_name": "销售金额",
                "description": "按月统计销售金额",
            }
        )
        self._ensure_chart(
            {
                **common,
                "sequence": 30,
                "name": "销售员业绩对比",
                "chart_code": "sale_by_user",
                "chart_type": "area",
                "group_by": "person",
                "measure_type": "sum",
                "measure_field_id": amount_field.id,
                "y_axis_name": "销售金额",
                "description": "按销售员统计销售金额",
            }
        )
        return "生成 销售图表：销售增长、销售金额、销售员业绩。"
