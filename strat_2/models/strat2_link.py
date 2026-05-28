"""Dynamic module linking — generic relationship layer for Strat 2.0.

When a ``strat2.module.link`` record is created, this module automatically
injects a notebook page into the form views of both linked models.

Each link creates per-link many2many fields on both models, so users can
link specific records directly from the form view via the standard
"Add a line" Odoo UI.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class Strat2ModuleLink(models.Model):
    """Definition of a dynamic link between two Odoo models."""

    _name = "strat2.module.link"
    _description = "Strat 2.0 Dynamic Module Link"
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
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        for vals in vals_list:
            model_a = vals.get("model_a", "")
            model_b = vals.get("model_b", "")
            if model_a and model_b:
                existing = self.sudo()._find_existing_link(model_a, model_b)
                if existing:
                    raise ValidationError(
                        f"A link between '{model_a}' and '{model_b}' already exists "
                        f"(link: '{existing.name}', ID: {existing.id}). "
                        f"Two models can only be linked once."
                    )

        records = super().create(vals_list)
        for record in records:
            if not record.page_name:
                record.page_name = record._model_label(record.model_b)
            for model_name in {record.model_a, record.model_b}:
                try:
                    record.sudo()._inject_views(model_name)
                except Exception:
                    _logger.exception(
                        "Strat 2: failed to inject views for %s", model_name
                    )
        return records

    # -- unlink hook (cleanup) -----------------------------------------------

    def unlink(self):
        """Remove injected views, custom fields, and relation tables."""
        for link in self:
            link.sudo()._cleanup_views_and_fields()
        return super().unlink()

    def _cleanup_views_and_fields(self):
        """Delete injected views, custom fields, and drop the relation table."""
        field_name = f"x_strat2_link_{self.id}"

        # 1. Remove injected views — search broadly by field name in arch
        #    to avoid missing views due to name mismatches.
        for model_name in {self.model_a, self.model_b}:
            # Try exact name first, then fall back to pattern search
            page_view_name = f"Strat 2 Link Page [{model_name}] ({self.name})"
            views = (
                self.env["ir.ui.view"]
                .sudo()
                .search(
                    [
                        "|",
                        ("name", "=", page_view_name),
                        "&",
                        ("model", "=", model_name),
                        ("arch_db", "ilike", field_name),
                    ]
                )
            )
            if views:
                views.unlink()
                _logger.info(
                    "Strat 2: removed %d views for link %s on %s",
                    len(views),
                    self.name,
                    model_name,
                )
            else:
                _logger.warning(
                    "Strat 2: no views found for link %s on %s (field=%s)",
                    self.name,
                    model_name,
                    field_name,
                )

        # 2. Remove custom many2many fields via SQL to avoid ORM cascade errors.
        custom_fields = (
            self.env["ir.model.fields"]
            .sudo()
            .search(
                [
                    ("name", "=", field_name),
                    ("model", "in", [self.model_a, self.model_b]),
                ]
            )
        )
        if custom_fields:
            # Delete metadata via SQL — bypasses ORM trigger cascade
            self.env.cr.execute(
                "DELETE FROM ir_model_fields WHERE id IN %s",
                (tuple(custom_fields.ids),),
            )
            _logger.info(
                "Strat 2: removed field %s from models",
                field_name,
            )
        else:
            _logger.warning(
                "Strat 2: no ir.model.fields records found for %s", field_name
            )

        # 3. Schedule relation table for cleanup.
        #    We do NOT drop it now because the field may still be referenced
        #    in Odoo's Python _fields registry until the next server restart.
        #    Dropping it would cause UndefinedTable errors on page refresh.
        #    Instead, truncate the table (remove any rows) and leave it empty.
        rel_table = f"x_strat2_link_{self.id}_rel"
        try:
            self.env.cr.execute("SELECT to_regclass(%s)", (rel_table,))
            if self.env.cr.fetchone()[0]:
                self.env.cr.execute(f'TRUNCATE "{rel_table}" CASCADE')
                _logger.info(
                    "Strat 2: truncated relation table %s (will be dropped on restart)",
                    rel_table,
                )
        except Exception:
            _logger.exception(
                "Strat 2: failed to truncate relation table %s", rel_table
            )

        # 4. Invalidate Odoo caches so the next page load picks up the changes.
        #    View deletions and field removal via SQL don't automatically
        #    clear the ORM's view/field caches.
        try:
            self.env["ir.ui.view"].sudo().clear_caches()
        except Exception:
            _logger.debug("Strat 2: could not clear ir.ui.view caches")

    # -- duplicate check -----------------------------------------------------

    def _find_existing_link(self, model_a, model_b):
        """Check if a link already exists between two models (in either direction).

        Returns the existing link recordset or empty recordset.
        """
        return self.sudo().search(
            [
                "|",
                "&",
                ("model_a", "=", model_a),
                ("model_b", "=", model_b),
                "&",
                ("model_a", "=", model_b),
                ("model_b", "=", model_a),
            ],
            limit=1,
        )

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
            _logger.info("Strat 2: no form view for %s, skipping", model_name)
            return

        ir_model = self.env["ir.model"]._get(model_name)
        if not ir_model:
            return

        has_notebook = "<notebook" in (form_view.arch or "")

        if model_name == self.model_a:
            comodel_name = self.model_b
            page_label = self.page_name or self._model_label(self.model_b)
        else:
            comodel_name = self.model_a
            page_label = self._model_label(self.model_a)

        # 1) Create per-link many2many field (idempotent)
        field_name = f"x_strat2_link_{self.id}"
        self._ensure_many2many_field(ir_model, field_name, comodel_name)

        # 2) Inject notebook page (once per link per model)
        page_view_name = f"Strat 2 Link Page [{model_name}] ({self.name})"
        if not self.env["ir.ui.view"].search(
            [("model", "=", model_name), ("name", "=", page_view_name)],
            limit=1,
        ):
            self._create_notebook_page(
                model_name, form_view.id, field_name, page_label, has_notebook
            )

        _logger.info(
            "Strat 2: injected link %s into %s (field=%s, notebook=%s)",
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
        rel_table = f"x_strat2_link_{self.id}_rel"
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
        """Inject a <page> inside <notebook> showing the many2many field."""
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
                f'<page string="{page_label}" name="strat2_link_{self.id}">'
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
                f'<page string="{page_label}" name="strat2_link_{self.id}">'
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
                "name": f"Strat 2 Link Page [{model_name}] ({self.name})",
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
