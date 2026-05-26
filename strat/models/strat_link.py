"""Dynamic module linking — generic relationship layer.

When Strat creates a ``strat.module.link`` record, this module automatically
injects a notebook page into the form views of both linked models.

Each link creates per-link many2many fields on both models, so users can
link specific records directly from the form view via the standard
"Add a line" Odoo UI.

Strat creates links through MCP CRUD:
* ``create_record("strat.module.link", ...)`` — define a link type (triggers
  field creation + view injection on both models)
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
        """Create many2many field + notebook page on the target model."""
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

        has_notebook = "<notebook" in (form_view.arch or "")

        # Determine the other model (the one we point to)
        if model_name == self.model_a:
            comodel_name = self.model_b
            page_label = self.page_name or self._model_label(self.model_b)
        else:
            comodel_name = self.model_a
            page_label = self._model_label(self.model_a)

        # 1) Create per-link many2many field (idempotent)
        field_name = f"x_strat_link_{self.id}"
        self._ensure_many2many_field(ir_model, field_name, comodel_name)

        # 2) Inject notebook page (once per link per model)
        page_view_name = f"Strat Link Page [{model_name}] ({self.name})"
        if not self.env["ir.ui.view"].search(
            [("model", "=", model_name), ("name", "=", page_view_name)],
            limit=1,
        ):
            self._create_notebook_page(
                model_name, form_view.id, field_name, page_label, has_notebook
            )

        _logger.info(
            "Strat: injected link %s into %s (field=%s, notebook=%s)",
            self.name,
            model_name,
            field_name,
            has_notebook,
        )

    # -- helpers (field creation) --------------------------------------------

    def _ensure_many2many_field(self, ir_model, field_name, comodel_name):
        """Create a per-link many2many field on the target model."""
        if self.env["ir.model.fields"].search(
            [("model_id", "=", ir_model.id), ("name", "=", field_name)],
            limit=1,
        ):
            return

        model_table = ir_model.model.replace(".", "_")
        comodel_table = comodel_name.replace(".", "_")
        rel_table = f"x_strat_link_{self.id}_rel"
        col1 = f"x_{model_table}_id"
        col2 = f"x_{comodel_table}_id"

        comodel_ir = self.env["ir.model"]._get(comodel_name)
        comodel_label = comodel_ir.name if comodel_ir else comodel_name

        self.env["ir.model.fields"].create(
            {
                "model_id": ir_model.id,
                "name": field_name,
                "field_description": comodel_label,
                "ttype": "many2many",
                "relation": comodel_name,
                "relation_table": rel_table,
                "column1": col1,
                "column2": col2,
            }
        )

    # -- helpers (view injection) --------------------------------------------

    def _create_notebook_page(
        self, model_name, form_view_id, field_name, page_label, has_notebook
    ):
        """Inject a <page> inside <notebook> showing the many2many field.

        create="0" prevents creating new target records, but the standard
        many2many "Add a line" still lets users pick existing records.
        """
        comodel = self.model_b if model_name == self.model_a else self.model_a
        list_view = self.env["ir.ui.view"].search(
            [
                ("model", "=", comodel),
                ("type", "=", "list"),
                ("inherit_id", "=", False),
            ],
            limit=1,
            order="priority",
        )

        if list_view:
            page_arch = (
                f'<page string="{page_label}" name="strat_link_{self.id}">'
                f'<field name="{field_name}">'
                f"</field>"
                f"</page>"
            )
        else:
            inline_list = (
                '<list string="Linked Records" create="0" delete="0">'
                '<field name="display_name" string="Name"/>'
                "</list>"
            )
            page_arch = (
                f'<page string="{page_label}" name="strat_link_{self.id}">'
                f'<field name="{field_name}">'
                f"{inline_list}"
                f"</field>"
                f"</page>"
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
