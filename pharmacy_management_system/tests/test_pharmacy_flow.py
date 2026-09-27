from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPharmacyFlow(TransactionCase):

    def test_drug_auto_creates_pos_product(self):
        drug = self.env['pharmacy.drug'].create({
            'name': 'Test Paracetamol',
            'sale_price': 7.5,
        })
        self.assertTrue(drug.product_id, "A product should be auto-created for the drug")
        product = drug.product_id
        self.assertEqual(product.name, 'Test Paracetamol')
        self.assertEqual(product.list_price, 7.5)
        self.assertTrue(product.available_in_pos, "Drug product must be sellable in the POS")
        self.assertTrue(product.is_storable, "Drug product must track stock")
        medicines = product.pos_categ_ids.filtered(lambda c: c.name == 'Medicines')
        self.assertTrue(medicines, "Drug product should belong to the Medicines POS category")

        # Rename / reprice keeps the product in sync
        drug.write({'name': 'Test Paracetamol Forte', 'sale_price': 9.0})
        self.assertEqual(product.name, 'Test Paracetamol Forte')
        self.assertEqual(product.list_price, 9.0)

    def test_branch_auto_provisions_pos_register(self):
        company = self.env.company
        top = self.env['stock.location'].create({
            'name': 'Test Locations',
            'usage': 'view',
            'company_id': company.id,
        })
        warehouse = self.env['stock.warehouse'].create({
            'name': 'Test Pharmacy WH',
            'code': 'TPW',
            'view_location_id': top.id,
        })
        shelf = self.env['stock.location'].create({
            'name': 'Test Branch Shelves',
            'usage': 'internal',
            'location_id': top.id,
            'company_id': company.id,
        })
        branch = self.env['pharmacy.pharmacy'].create({
            'name': 'Test Branch',
            'code': 'TB1',
            'warehouse_id': warehouse.id,
            'location_id': shelf.id,
        })
        self.assertTrue(branch.pos_config_id, "A POS register should be auto-created")
        config = branch.pos_config_id
        self.assertEqual(config.picking_type_id.default_location_src_id, shelf,
                         "Register deliveries must source from the branch location")
        self.assertTrue(config.payment_method_ids, "Register needs at least one payment method")
        self.assertTrue(config.iface_print_auto, "Register should auto-print receipts")

    def test_coverage_shortage_alert(self):
        drug = self.env['pharmacy.drug'].create({'name': 'Shortage Drug', 'sale_price': 5.0})
        coverage = self.env['pharmacy.drug.coverage'].create({
            'drug_id': drug.id,
            'pharmacy_id': self.env['pharmacy.pharmacy'].search([], limit=1).id,
            'min_qty': 10,
        })
        self.assertEqual(coverage.current_qty, 0.0)
        self.assertTrue(coverage.shortage_flag, "Coverage below minimum must raise a shortage alert")
        # Search support for the Shortage Alerts screen
        found = self.env['pharmacy.drug.coverage'].search([('shortage_flag', '=', True), ('id', '=', coverage.id)])
        self.assertIn(coverage, found)

    def test_prescription_flow(self):
        patient = self.env['res.partner'].create({'name': 'Test Patient', 'is_patient': True})
        doctor = self.env['res.partner'].create({
            'name': 'Dr. Test', 'is_doctor': True, 'license_number': 'T-0001',
        })
        drug = self.env['pharmacy.drug'].create({'name': 'Rx Drug', 'sale_price': 10.0})
        branch = self.env['pharmacy.pharmacy'].search([], limit=1)
        prescription = self.env['pharmacy.prescription'].create({
            'patient_id': patient.id,
            'doctor_id': doctor.id,
            'pharmacy_id': branch.id,
            'line_ids': [Command.create({'drug_id': drug.id, 'qty_prescribed': 2})],
        })
        self.assertEqual(prescription.state, 'draft')
        prescription.action_mark_done()
        self.assertEqual(prescription.state, 'done')
        with self.assertRaises(UserError):
            prescription.action_cancel()
