import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { useSetupAction } from "@web/search/action_hook";
import { standardViewProps } from "@web/views/standard_view_props";
import { usePager } from "@web/search/pager_hook";
import { GalleryModel } from "./gallery_model";
import { GalleryRenderer } from "./gallery_renderer";

export class GalleryController extends Component {
    static template = "awesome_gallery.GalleryController";
    static components = { Layout };
    static props = {
        ...standardViewProps,
        Model: Function,
        Renderer: Function,
        imageField: String,
        tooltipField: { type: String, optional: true },
        tooltipTemplate: { type: Object, optional: true },
        fieldsForTooltip: { type: Array, optional: true },
        limit: { type: Number, optional: true },
        archInfo: { type: Object, optional: true },
    };

    setup() {
        useSetupAction();

        this.model = new this.props.Model(this.env, {
            resModel: this.props.resModel,
            imageField: this.props.imageField,
            tooltipField: this.props.tooltipField,
            fieldsForTooltip: this.props.fieldsForTooltip,
            limit: this.props.limit || 80,
        });

        usePager(() => {
            return {
                offset: this.model.pager.offset,
                limit: this.model.pager.limit,
                total: this.model.pager.total,
                onUpdate: async ({ offset, limit }) => {
                    this.model.pager.offset = offset;
                    this.model.pager.limit = limit;
                    await this.model.loadImages(this.props.domain);
                    this.render(true);
                },
            };
        });

        onWillStart(async () => {
            await this.model.loadImages(this.props.domain);
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.domain !== this.props.domain) {
                this.model.pager.offset = 0;
            }
            await this.model.loadImages(nextProps.domain);
        });
    }

    get display() {
        return {
            ...this.props.display,
            controlPanel: {
                ...this.props.display?.controlPanel,
            },
        };
    }

    switchToFormView(recordId) {
        this.env.services.action.switchView("form", { resId: recordId });
    }

    async onImageUploaded(recordId, base64) {
        await this.env.services.orm.webSave(this.props.resModel, [recordId], {
            [this.props.imageField]: base64,
        });
        await this.model.loadImages(this.props.domain);
        this.render(true);
    }
}
