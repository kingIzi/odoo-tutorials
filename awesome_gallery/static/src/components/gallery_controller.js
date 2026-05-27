/** @odoo-module alias="awesome_gallery.gallery_controller" */

import { Component } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { useSetupAction } from "@web/search/action_hook";
import { standardViewProps } from "@web/views/standard_view_props";

export class GalleryController extends Component {
    static template = "awesome_gallery.GalleryController";
    static components = { Layout };
    static props = {
        ...standardViewProps,
    };

    setup() {
        useSetupAction();
    }

    get display() {
        return {
            ...this.props.display,
            controlPanel: {
                ...this.props.display?.controlPanel,
            },
        };
    }
}
