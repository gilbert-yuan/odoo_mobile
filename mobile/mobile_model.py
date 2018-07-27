# -*- coding: utf-8 -*-
import jinja2, sys, os
import simplejson, openerp
from openerp.addons.web.controllers.main import ensure_db
from openerp import http
from openerp.http import request
from openerp.osv import fields, osv
import copy
import datetime
from openerp.tools import float_round
import tempfile
import os
from dateutil.relativedelta import relativedelta

ISODATEFORMAT = '%Y-%m-%d'
ISODATETIMEFORMAT = "%Y-%m-%d %H:%M:%S"
MOBILEDATETIMEFORMAT = "%Y-%m-%d %H:%M"
SUPERUSER_ID = 1

if hasattr(sys, 'frozen'):
    # When running on compiled windows binary, we don't have access to package loader.
    path = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'html'))
    loader = jinja2.FileSystemLoader(path)
else:
    loader = jinja2.PackageLoader('openerp.addons.mobile', "html")

env = jinja2.Environment('<%', '%>', '${', '}', '%', loader=loader, autoescape=True)


class MobileGridLabel(osv.osv):
    """

    """
    _name = 'mobile.grid.label'

    _columns = {
        'name': fields.char(u'名称'),
        'sequence': fields.integer(u'顺序'),
    }


class MobileAction(osv.osv):
    _name = 'mobile.action'
    _rec_name = 'mobile_grid_id'

    def _compute_mobile_view_id(self, cr, uid, ids, name, args, context=None):
        res = {}
        for action_id in ids:
            view_id = self.pool.get('mobile.view').search(cr, uid, [('mobile_action_id', '=', action_id)],
                                                          context=context)
            res[action_id] = view_id and view_id[0]
        return res

    _columns = {
        'model_id': fields.many2one('ir.model', u'模型名称'),
        'name': fields.char(u'名称'),
        'limit': fields.integer('limit'),
        'offset': fields.integer('offset'),
        'order': fields.char('order'),
        'context': fields.char('context'),
        'mobile_grid_id': fields.many2one('mobile.grid', u'Grid ID'),
        'mobile_view_id': fields.function(_compute_mobile_view_id, type='many2one', relation='mobile.view',
                                          string=u'Grid ID')
    }
    _sql_constraints = [
        ('model_mobile_grid_id_field_id_uniq', 'unique (mobile_grid_id)', u'一个菜单只能对应一个动作'),
    ]
    _defaults = {
        'limit': 6,
        'offset': 0,
        'order': 'id DESC',
        'context': '{}',
    }


class MobileView(osv.osv):
    _name = 'mobile.view'
    _rec_name = 'name'

    _columns = {
        'name': fields.char(u'视图名称'),
        'mobile_action_id': fields.many2one('mobile.action', u'动作'),
        'mobile_field_ids': fields.one2many('mobile.field', 'view_id', string=u'视图表', copy=True),
        'no_form': fields.boolean(u'不显示form', help="视图类型是card的，不推荐再次显示form"),
        'model_id': fields.many2one('ir.model', u'模型名称', copy=True),
        'domain_ids': fields.one2many('mobile.domain', 'view_id', string="domain", copy=True),
        'view_type': fields.selection([('tree', u'列表视图'), ('card', u'看板'), ('bar', '条形图'), ('pie', '饼状图'),
                                       ('view_form', u'表单'), ('edit_form', '编辑表单')], u'view type',
                                      help="", copy=True),
        'button_ids': fields.one2many('mobile.button', 'view_id', string='buttons', copy=True, help="这个地方的按钮主要是针对，"),
        'show_form_view': fields.many2one('mobile.view', u'新建编辑视图', copy=True),
        'context': fields.text(u'附加值'),
    }
    _defaults = {
        'no_form': True
    }

    _sql_constraints = [
        ('model_mobile_action_id_field_id_uniq', 'unique (mobile_action_id)', u'一个动作只能对应一个主视图'),
    ]


class One2ManyField(osv.osv):
    _name = 'one.many.field'
    _columns = {
        'mobile_field_ids': fields.one2many('mobile.field', 'view_id', string=u'视图表'),
    }


class MobileDomain(osv.osv):
    _name = 'mobile.domain'
    _order = 'sequence'
    _columns = {
        'view_id': fields.many2one('mobile.view', string='view', copy=True),
        'domain': fields.char(u'domain', copy=True),
        'need_badge': fields.boolean(u'需要显示条数'),
        'sequence': fields.integer(u'顺序', copy=True),
        'group_ids': fields.many2many('res.groups', 'domain_groups_rel', 'domain_id', 'group_id', string='用户组'),
        'name': fields.char(u'名称', copy=True)
    }


class MobileButton(osv.osv):
    _name = 'mobile.button'
    _columns = {
        'name': fields.char(u'名称', copy=True),
        'style': fields.selection([('default', u'默认'), ('primary', 'primary')], string='样式', copy=True),
        'button_method': fields.char(u'方法名', copy=True),
        'show_condition': fields.char(u'显示前提', copy=True),
        'view_id': fields.many2one('mobile.view', string=u'视图', copy=True),
        'group_ids': fields.many2many('res.groups', 'button_groups_rel', 'button_id', 'group_id', string='用户组'),
    }
    _defaults = {
        'show_condition': []
    }


class MobileField(osv.osv):
    _name = 'mobile.field'
    _order = 'sequence'
    _columns = {
        'group_ids': fields.many2many('res.groups', 'field_groups_rel', 'button_id', 'group_id', string='用户组'),
        'sequence': fields.integer(u'序列'),
        'view_id': fields.many2one('mobile.view', u'视图ID', copy=True),
        'ir_field': fields.many2one('ir.model.fields', u'字段', copy=True),
        'domain': fields.char(u'domain'),
        'field_type': fields.related('ir_field', 'ttype', type='char', string=u'字段类型', readonly=True, copy=True),
        'field_relation': fields.related('ir_field', 'relation', type='char', string=u'字段关联', readonly=True, copy=True),
        'field_selection': fields.related('ir_field', 'selection', type='char', string=u'选择项目', readonly=True,
                                          copy=True),
        'model_id': fields.many2one('ir.model', string=u'类型', copy=True),
        'required': fields.char(u'必输', copy=True),
        'readonly': fields.char(u'只读', copy=True),
        'invisible': fields.char(u'不可见', copy=True),
        'is_show_edit_form': fields.boolean(u'form不可见', copy=True),
        'is_show_form_tree': fields.boolean(u'tree不可见', copy=True),
        'field_id': fields.many2one('mobile.field', 'field_id', copy=True),
        'many_field': fields.one2many('mobile.field', 'field_id', string='one2many', copy=True)
    }


class MobileGrid(osv.osv):
    _name = 'mobile.grid'
    _rec_name = 'title'
    _order = 'sequence'

    def _compute_mobile_action_id(self, cr, uid, ids, name, args, context=None):
        res = {}
        for grid_id in ids:
            action_id = self.pool.get('mobile.action').search(cr, uid, [('mobile_grid_id', '=', grid_id)],
                                                              context=context)
            res[grid_id] = action_id and action_id[0]
        return res

    _columns = {
        'label_id': fields.many2one('mobile.grid.label', u'分类', required=True),
        'sequence': fields.related('label_id', 'sequence', type='integer', string=u'顺序', readonly=True),
        'image': fields.binary(u'图片', required=True),
        'mobile_action_id': fields.function(_compute_mobile_action_id, type='many2one', relation='mobile.action',
                                            string=u'动作'),
        'title': fields.char(u'名称', required=True),
        'group_ids': fields.many2many('res.groups', 'mobile_groups_rel', 'grid_id', 'group_id', string='用户组'),

    }
