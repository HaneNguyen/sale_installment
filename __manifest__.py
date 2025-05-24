{
    'name': 'Sale Installment',
    'version': '18.0.0.1.0',
    'summary': 'Quản lý đơn hàng trả góp/trả chậm',
    'description': 'Mở rộng sale_management để xử lý hồ sơ trả góp, duyệt tài chính và tạo hợp đồng.',
    'author': 'NHOM 2',
    'category': 'Sales',
    'depends': ['sale_management', 'mail', 'sale'],  # kế thừa sale_management
    'data': [
        'security/ir.model.access.csv',
        'reports/contract_template.xml',
        'data/ir_sequence_data.xml',
        'data/email_template.xml',
        'views/installment_profile_view.xml',
        'views/sale_order_view.xml',
    ],
    'installable': True,
    'application': True,
}