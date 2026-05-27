/** @odoo-module alias="awesome_gallery.gallery_view" */

import { registry } from "@web/core/registry";
import { GalleryController } from "./gallery_controller";

export const galleryView = {
    type: "gallery",
    display_name: "Gallery",
    icon: "oi oi-view-list",
    multiRecord: true,
    Controller: GalleryController,

    props: (genericProps, view) => {
        return {
            ...genericProps,
            Controller: view.Controller,
        };
    },
};

registry.category("views").add("gallery", galleryView);
