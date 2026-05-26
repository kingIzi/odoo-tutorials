"""Dynamic module linking — generic relationship layer.

When Strat creates a ``strat.module.link`` record, this module automatically
injects a notebook page into the form views of both linked models showing
linked records inline, plus a "Links" smart button with a count.

Strat uses the wrapper through standard MCP CRUD calls:

* ``create_record("strat.module.link", ...)``  — define a link type
* ``create_record("strat.module.link.line", ...)``  — link specific records
* ``search_records("strat.module.link.line", ...)``  — query linked records
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


# =====================================================================
# Link definition
# =====================================================================


class StratModuleLink(models.Model):
    """Definition of a dynamic link between two Odoo models."""

    _name = "strat.module.link"
    _description = "Dynamic Module Link"
    _order = "name"

    name = fields.Char(required=True, help="Human-readable label for this link type")
    model_a = fields.Char(
        required=True,
        string="Model A",
        help="Technical name of the first model, e.g. 'hr.employee'",
    )
    model_b = fields.Char(
        required=True,
        string="Model B",
        help="Technical name of the second model, e.g. 'estate.property'",
    )
    page_name = fields.Char(
        help="Label shown on the form tab (auto-generated if empty)",
    )
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        "strat.module.link.line",
        "link_id",
        string="Linked Records",
    )
    line_count = fields.Integer(compute="_compute_line_count")

    # -- computed ------------------------------------------------------------

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    # -- create hook ---------------------------------------------------------

    @api.model
    def create(self, vals):
        record = super().create(vals)
        if not record.page_name:
            record.page_name = record._model_label(record.model_b)
        for model_name in {record.model_a, record.model_b}:
            try:
                record.sudo()._inject_views(model_name)
            except Exception:
                _logger.exception("Strat: failed to inject views for %s", model_name)
        return record

    # -- view injection ------------------------------------------------------

    def _inject_views(self, model_name):
        """Create fields + server action + smart button + notebook page."""
        form_view = self.env["ir.ui.view"].search(
            [
                ("model", "=", model_name),
                ("type", "=", "form"),
                ("inherit_id", "=", False),
            ],
            limit=1,
            order="priority",
        )
        if not form_view:
            _logger.info("Strat: no form view for %s, skipping", model_name)
            return

        ir_model = self.env["ir.model"]._get(model_name)
        if not ir_model:
            return

        has_button_box = "button_box" in (form_view.arch or "")
        has_notebook = "<notebook" in (form_view.arch or "")

        # 1) Fields — idempotent (skip if already created)
        self._ensure_count_field(ir_model)
        self._ensure_link_lines_field(ir_model)

        # 2) Smart button — once per model
        if not self.env["ir.ui.view"].search(
            [("model", "=", model_name), ("name", "=", f"Strat Links [{model_name}]")],
            limit=1,
        ):
            sa = self._create_server_action(ir_model, model_name)
            self._create_inherited_view(model_name, form_view.id, sa.id, has_button_box)

        # 3) Notebook page — once per link type per model
        page_view_name = f"Strat Link Page [{model_name}] ({self.name})"
        if not self.env["ir.ui.view"].search(
            [("model", "=", model_name), ("name", "=", page_view_name)],
            limit=1,
        ):
            self._create_notebook_page(model_name, form_view.id, has_notebook)

        _logger.info(
            "Strat: injected links into %s (button_box=%s, notebook=%s)",
            model_name,
            has_button_box,
            has_notebook,
        )

    # -- helpers (field creation) --------------------------------------------

    def _ensure_count_field(self, ir_model):
        """Create ``x_strat_link_count`` on the target model if missing."""
        if self.env["ir.model.fields"].search(
            [("model_id", "=", ir_model.id), ("name", "=", "x_strat_link_count")],
            limit=1,
        ):
            return
        self.env["ir.model.fields"].create(
            {
                "model_id": ir_model.id,
                "name": "x_strat_link_count",
                "field_description": "Links",
                "ttype": "integer",
                "store": True,
            }
        )

    def _ensure_link_lines_field(self, ir_model):
        """Create ``x_strat_link_lines`` many2many on the target model if missing.

        Uses a stored many2many (no compute) — the field is synced manually
        when link lines are created/deleted, same pattern as x_strat_link_count.
        """
        if self.env["ir.model.fields"].search(
            [("model_id", "=", ir_model.id), ("name", "=", "x_strat_link_lines")],
            limit=1,
        ):
            return

        model_name = ir_model.model
        comodel = "strat.module.link.line"
        # Generate standard many2many relation table/column names
        rel_name = f"{model_name.replace('.', '_')}_strat_link_lines_rel"
        col1 = f"{model_name.replace('.', '_')}_id"
        col2 = "strat_module_link_line_id"

        self.env["ir.model.fields"].create(
            {
                "model_id": ir_model.id,
                "name": "x_strat_link_lines",
                "field_description": "Linked Records",
                "ttype": "many2many",
                "relation": comodel,
                "relation_table": rel_name,
                "column1": col1,
                "column2": col2,
            }
        )

    # -- helpers (view injection) --------------------------------------------

    def _create_server_action(self, ir_model, model_name):
        code = (
            f"model_name = '{model_name}'\n"
            "res_id = records[:1].id\n"
            "if res_id:\n"
            "    links = env['strat.module.link.line'].search([\n"
            "        '|',\n"
            "        '&', ('link_id.model_a', '=', model_name), ('res_id_a', '=', res_id),\n"
            "        '&', ('link_id.model_b', '=', model_name), ('res_id_b', '=', res_id),\n"
            "    ])\n"
            "    action = {\n"
            "        'type': 'ir.actions.act_window',\n"
            "        'name': 'Linked Records',\n"
            "        'res_model': 'strat.module.link.line',\n"
            "        'view_mode': 'list',\n"
            "        'domain': [('id', 'in', links.ids)],\n"
            "    }\n"
        )
        return self.env["ir.actions.server"].create(
            {
                "name": f"Strat: View Links ({model_name})",
                "model_id": ir_model.id,
                "state": "code",
                "code": code,
            }
        )

    def _create_inherited_view(self, model_name, form_view_id, sa_id, has_button_box):
        if has_button_box:
            xpath = '<xpath expr="//div[@name=\'button_box\']" position="inside">'
        else:
            xpath = '<xpath expr="//sheet" position="inside">'

        if has_button_box:
            button = (
                '<button class="oe_stat_button" icon="fa-link" '
                f'type="action" name="{sa_id}">'
                '<field name="x_strat_link_count" widget="statinfo" '
                'string="Links"/>'
                "</button>"
            )
            close_xpath = "</xpath>"
        else:
            button = (
                '<div class="oe_button_box" name="button_box">'
                '<button class="oe_stat_button" icon="fa-link" '
                f'type="action" name="{sa_id}">'
                '<field name="x_strat_link_count" widget="statinfo" '
                'string="Links"/>'
                "</button>"
                "</div>"
            )
            close_xpath = "</xpath>"

        arch = "<data>" + xpath + button + close_xpath + "</data>"
        self.env["ir.ui.view"].create(
            {
                "name": f"Strat Links [{model_name}]",
                "model": model_name,
                "inherit_id": form_view_id,
                "arch": arch,
            }
        )

    def _create_notebook_page(self, model_name, form_view_id, has_notebook):
        """Inject a <page> inside <notebook> showing linked records."""
        if model_name == self.model_a:
            target_field = "name_b"
            page_label = self.page_name or self._model_label(self.model_b)
        else:
            target_field = "name_a"
            page_label = self._model_label(self.model_a)

        inline_list = (
            '<list string="Linked Records" create="0" delete="0">'
            f'<field name="{target_field}" string="{page_label}"/>'
            "</list>"
        )

        domain = (
            f"[('link_id', '=', {self.id}),"
            f"('link_id.model_a', '=', '{self.model_a}'),"
            f"('link_id.model_b', '=', '{self.model_b}')]"
        )

        page_arch = (
            f'<page string="{page_label}" name="strat_link_{self.id}">'
            f'<field name="x_strat_link_lines" domain="{domain}">'
            f"{inline_list}"
            "</field>"
            "</page>"
        )

        if has_notebook:
            xpath = '<xpath expr="//notebook" position="inside">'
            arch = "<data>" + xpath + page_arch + "</xpath></data>"
        else:
            notebook = "<notebook>" + page_arch + "</notebook>"
            xpath = '<xpath expr="//sheet" position="inside">'
            arch = "<data>" + xpath + notebook + "</xpath></data>"

        self.env["ir.ui.view"].create(
            {
                "name": f"Strat Link Page [{model_name}] ({self.name})",
                "model": model_name,
                "inherit_id": form_view_id,
                "arch": arch,
            }
        )

    # -- helpers (general) ---------------------------------------------------

    def _model_label(self, model_name):
        try:
            ir = self.env["ir.model"].search([("model", "=", model_name)], limit=1)
            if ir.name:
                return ir.name
        except Exception:
            pass
        return model_name.split(".")[-1].replace("_", " ").title()


# =====================================================================
# Individual link (record-to-record pair)
# =====================================================================


class StratModuleLinkLine(models.Model):
    """A single link between two records across models."""

    _name = "strat.module.link.line"
    _description = "Dynamic Module Link Line"
    _order = "id desc"

    _sql_constraints = [
        (
            "unique_pair",
            "UNIQUE(link_id, res_id_a, res_id_b)",
            "These two records are already linked.",
        ),
    ]

    link_id = fields.Many2one(
        "strat.module.link",
        required=True,
        ondelete="cascade",
    )
    res_id_a = fields.Integer(required=True, string="Record A")
    res_id_b = fields.Integer(required=True, string="Record B")
    name_a = fields.Char(compute="_compute_names", store=True)
    name_b = fields.Char(compute="_compute_names", store=True)

    # -- computed ------------------------------------------------------------

    @api.depends("link_id", "res_id_a", "res_id_b")
    def _compute_names(self):
        for line in self:
            ma = line.link_id.model_a if line.link_id else ""
            mb = line.link_id.model_b if line.link_id else ""
            line.name_a = line._record_display(ma, line.res_id_a)
            line.name_b = line._record_display(mb, line.res_id_b)

    # -- create / unlink hooks -----------------------------------------------

    @api.model
    def create(self, vals):
        record = super().create(vals)
        record._sync_linked_records(adding=True)
        return record

    def unlink(self):
        self._sync_linked_records(adding=False)
        return super().unlink()

    def _sync_linked_records(self, adding=True):
        """Keep ``x_strat_link_count`` and ``x_strat_link_lines`` in sync
        on both end records whenever a link line is created or deleted."""
        for line in self:
            link = line.link_id
            if not link:
                continue
            for model_name, res_id in [
                (link.model_a, line.res_id_a),
                (link.model_b, line.res_id_b),
            ]:
                try:
                    rec = self.env[model_name].browse(res_id)
                    if not rec.exists():
                        continue

                    # Sync count
                    current = getattr(rec, "x_strat_link_count", 0) or 0
                    if adding:
                        rec.x_strat_link_count = current + 1
                    else:
                        rec.x_strat_link_count = max(0, current - 1)

                    # Sync many2many
                    if adding:
                        rec.write({"x_strat_link_lines": [(4, line.id)]})
                    else:
                        rec.write({"x_strat_link_lines": [(3, line.id)]})

                except Exception:
                    _logger.exception(
                        "Strat: failed to sync link fields on %s/%s",
                        model_name,
                        res_id,
                    )

    # -- helpers -------------------------------------------------------------

    def _record_display(self, model_name, res_id):
        if not model_name:
            return str(res_id)
        try:
            rec = self.env[model_name].browse(res_id)
            if rec.exists():
                return rec.display_name or str(res_id)
        except Exception:
            pass
        return str(res_id)
