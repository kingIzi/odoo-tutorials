import { Component, xml } from "@odoo/owl";
import { url } from "@web/core/utils/urls";
import { FileUploader } from "@web/views/fields/file_handler";

const TOOLTIP_TEMPLATE_NAME = "awesome_gallery.advanced_tooltip";

export class GalleryRenderer extends Component {
    static template = "awesome_gallery.GalleryRenderer";
    static components = { FileUploader };
    static props = {
        data: Array,
        resModel: String,
        imageField: String,
        tooltipField: { type: String, optional: true },
        tooltipTemplate: { type: Object, optional: true },
        fieldsForTooltip: { type: Array, optional: true },
        onImageClick: Function,
        onImageUploaded: Function,
    };

    setup() {
        this._setupTooltipTemplate();
    }

    _setupTooltipTemplate() {
        if (!this.props.tooltipTemplate) {
            return;
        }

        const templateEl = this.props.tooltipTemplate.cloneNode(true);
        const fieldNodes = templateEl.querySelectorAll("field");
        for (const fieldNode of fieldNodes) {
            const fieldName = fieldNode.getAttribute("name");
            const tEsc = document.createElement("t");
            tEsc.setAttribute("t-esc", `info.${fieldName}`);
            fieldNode.replaceWith(tEsc);
        }

        const innerContent = templateEl.innerHTML;
        const owlTemplate = xml`<t t-name="${TOOLTIP_TEMPLATE_NAME}"><div>${innerContent}</div></t>`;

        // Register the template through the Owl app so the tooltip service can find it
        if (this.__owl__ && this.__owl__.app) {
            this.__owl__.app.addTemplate(TOOLTIP_TEMPLATE_NAME, owlTemplate);
        }
    }

    getImageUrl(record) {
        const params = {
            model: this.props.resModel,
            id: record.id,
            field: this.props.imageField,
        };
        if (record.write_date) {
            params.write_date = record.write_date;
        }
        return url("/web/image", params);
    }

    getTooltipValue(record) {
        if (!this.props.tooltipField) {
            return "";
        }
        const value = record[this.props.tooltipField];
        if (value && typeof value === "object") {
            return value[1] || value.display_name || String(value);
        }
        return value != null ? String(value) : "";
    }

    getTooltipInfo(record) {
        const info = {};
        for (const key of Object.keys(record)) {
            const val = record[key];
            // For relational fields, get the display name
            if (val && typeof val === "object" && !Array.isArray(val)) {
                info[key] = val[1] || val.display_name || JSON.stringify(val);
            } else if (Array.isArray(val) && val.length === 2) {
                info[key] = val[1];
            } else {
                info[key] = val;
            }
        }
        return JSON.stringify(info);
    }

    onImageClick(recordId, ev) {
        if (
            ev.target.closest(".o_gallery_upload") ||
            ev.target.closest(".o_gallery_upload_btn")
        ) {
            return;
        }
        this.props.onImageClick(recordId);
    }

    async onFileUploaded(record, fileData) {
        if (fileData && fileData.data) {
            await this.props.onImageUploaded(record.id, fileData.data);
        }
    }
}
