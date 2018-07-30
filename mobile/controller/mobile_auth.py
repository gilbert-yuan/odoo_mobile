# -*- coding: utf-8 -*-
import simplejson
from odoo import http
from odoo.http import request
from odoo import models
SUPERUSER_ID = 1


# 拦截所有HTTP请求，检查是否有微信回调验证参数
# 有验证参数的话则进行验证，验证后跳转到业务页面
class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    # 重载url分发
    @classmethod
    def _dispatch(self):
        #检查是否有微信认证
        request.mobile = None
        auth = None
        #if auth == 'weixin' and not request.session.oauth_uid:
        #改成uid判断，否则PC上无法开发测试了
        if auth == 'mobile' and (not request.session or not request.session.uid):
            return request.make_response(simplejson.dumps({'error_code': 10004, 'error_message': u'未登录'}))
        return super(IrHttp, self)._dispatch()

    # 由@http.route注解指定auth='weixin'后自动调用
    @classmethod
    def _auth_method_mobile(self):
        request.uid = request.session.uid
        if request.mobile and not request.session.oauth_uid:
            raise http.AuthenticationError("Weixin not authentication")