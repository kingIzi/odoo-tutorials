import { registry } from "@web/core/registry";
import { GalleryController } from "./gallery_controller";
import { GalleryModel } from "./gallery_model";
import { GalleryRenderer } from "./gallery_renderer";
import { GalleryArchParser } from "./gallery_arch_parser";

const galleryArchParser = new GalleryArchParser();

export const galleryView = {
    type: "gallery",
    display_name: "Gallery",
    icon: "oi oi-view-list",
    multiRecord: true,
    Controller: GalleryController,
    Model: GalleryModel,
    Renderer: GalleryRenderer,
    archParser: galleryArchParser,

    props: (genericProps, view) => {
        const archInfo = view.archParser.parse(genericProps.arch);
        return {
            ...genericProps,
            Model: view.Model,
            Renderer: view.Renderer,
            Controller: view.Controller,
            imageField: archInfo.imageField,
            tooltipField: archInfo.tooltipField,
            tooltipTemplate: archInfo.tooltipTemplate,
            fieldsForTooltip: archInfo.fieldsForTooltip,
            limit: archInfo.limit,
            archInfo,
        };
    },
};

registry.category("views").add("gallery", galleryView);
