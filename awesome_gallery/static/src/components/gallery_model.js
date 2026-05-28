import { KeepLast } from "@web/core/utils/concurrency";

export class GalleryModel {
    constructor(env, params) {
        this.env = env;
        this.orm = env.services.orm;
        this.resModel = params.resModel;
        this.imageField = params.imageField;
        this.tooltipField = params.tooltipField;
        this.fieldsForTooltip = params.fieldsForTooltip || [];
        this.limit = params.limit || 80;
        this.keepLast = new KeepLast();

        this.data = [];
        this.pager = {
            offset: 0,
            limit: this.limit,
            total: 0,
        };
    }

    async loadImages(domain) {
        const specification = {
            [this.imageField]: {},
            write_date: {},
        };
        if (this.tooltipField) {
            specification[this.tooltipField] = {};
        }
        for (const field of this.fieldsForTooltip) {
            specification[field] = {};
        }

        const { length, records } = await this.keepLast.add(
            this.orm.webSearchRead(this.resModel, domain, {
                specification,
                limit: this.pager.limit,
                offset: this.pager.offset,
                context: {
                    bin_size: true,
                },
            }),
        );
        this.data = records;
        this.pager.total = length;
    }
}
