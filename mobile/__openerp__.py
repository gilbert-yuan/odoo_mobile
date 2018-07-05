# -*- coding: utf-8 -*-

{
    "name": "VUE 实现手机端的页面",
    "description":
        """
        手机端页面的配置实现
        因为要展示部分视图
        要用的pyechart
        要安装 pyechart pyecharts-snapshot 等重要等库
       必须  npm install -g phantomjs-prebuilt
        """,
    'author': "静静（gilbert@osbzr.com）",
    'website': "http://control.blog.sina.com.cn/blog_rebuild/profile/controllers/points_action.php",
    "category": "gilbert",
    "version": "8.0.0.1",
    "depends": ['base'],
    "data": [
        'mobile_model.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
}
