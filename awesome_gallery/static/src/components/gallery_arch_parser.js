import { visitXML } from "@web/core/utils/xml";

export class GalleryArchParser {
    parse(xmlDoc) {
        const imageField = xmlDoc.getAttribute("image_field");
        const tooltipField = xmlDoc.getAttribute("tooltip_field");
        const limit = parseInt(xmlDoc.getAttribute("limit") || "80", 10);

        const fieldsForTooltip = [];
        let tooltipTemplate = undefined;

        visitXML(xmlDoc, (node) => {
            if (node.tagName === "field") {
                fieldsForTooltip.push(node.getAttribute("name"));
            }
            if (node.tagName === "tooltip-template") {
                tooltipTemplate = node;
            }
        });

        return {
            imageField,
            tooltipField,
            limit,
            fieldsForTooltip,
            tooltipTemplate,
        };
    }
}
