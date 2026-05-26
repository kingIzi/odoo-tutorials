/** @odoo-module */
import { Component, useState, useRef, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class StratChat extends Component {
    static template = "strat.ChatWidget";

    setup() {
        this.state = useState({
            isOpen: false,
            messages: [],
            inputText: "",
            isLoading: false,
        });
        this.orm = useService("orm");
        this.action = useService("action");
        this.messageAreaRef = useRef("messageArea");

        onPatched(() => {
            const el = this.messageAreaRef.el;
            if (el) {
                // Render markdown into bot message bubbles
                el.querySelectorAll(".strat-bot-raw").forEach((node) => {
                    node.innerHTML = node.dataset.html;
                    node.classList.remove("strat-bot-raw");
                });
                el.scrollTop = el.scrollHeight;
            }
        });
    }

    async toggleChat() {
        this.state.isOpen = !this.state.isOpen;
        if (this.state.isOpen && !this.state.messages.length) {
            await this.loadMessages();
        }
    }

    async loadMessages() {
        try {
            const messages = await this.orm.call(
                "strat.message",
                "get_conversation",
                [],
            );
            this.state.messages = messages;
        } catch (e) {
            console.error("Strat: failed to load messages", e);
        }
    }

    async sendMessage() {
        const text = this.state.inputText.trim();
        if (!text || this.state.isLoading) return;

        this.state.messages.push({ is_user: true, message: text });
        this.state.inputText = "";
        this.state.isLoading = true;

        try {
            // Gather current page context (model + record being viewed)
            const context = this._getPageContext();

            const result = await this.orm.call(
                "strat.message",
                "send_and_respond",
                [],
                { message: text, context },
            );

            // Agent returns {response, changes}; fallback may return a string
            const responseText =
                typeof result === "string" ? result : result.response || "";
            const changes =
                typeof result === "object" && result.changes ? result.changes : [];

            this.state.messages.push({ is_user: false, message: responseText });

            // Live reload: if the agent modified records, refresh the current view
            if (changes.length) {
                this._reloadAffectedViews(changes);
            }
        } catch (error) {
            this.state.messages.push({
                is_user: false,
                message: "Sorry, something went wrong. Please try again.",
            });
        }

        this.state.isLoading = false;
    }

    /**
     * Reload the current Odoo view if it was affected by Strat's changes.
     *
     * Uses ``action.restore()`` which is the same mechanism Odoo's own
     * "soft_reload" client action uses — it re-renders the current controller
     * without a full page refresh.
     */
    _reloadAffectedViews(changes) {
        const controller = this.action.currentController;
        if (!controller) return;

        const currentModel = controller.props?.resModel;
        if (!currentModel) return;

        const affected = changes.some((c) => c.model === currentModel);
        if (!affected) return;

        // For form views, also check if a specific resId was affected
        const view = controller.view;
        if (view && !view.multiRecord) {
            const currentResId = controller.props?.resId;
            if (currentResId) {
                const relevantChanges = changes.filter((c) => c.model === currentModel);
                const allAffectedIds = relevantChanges.flatMap((c) => c.res_ids || []);
                // Reload if this specific record was changed, or if we
                // can't tell (empty res_ids — e.g. create with unknown ID)
                if (
                    allAffectedIds.length === 0 ||
                    allAffectedIds.includes(currentResId)
                ) {
                    this.action.restore(controller.jsId);
                }
            }
        } else {
            // List/kanban — always reload if the model was affected
            this.action.restore(controller.jsId);
        }
    }

    /**
     * Return the model and record ID of the currently displayed Odoo view.
     * Used to give Strat context about what the user is looking at.
     */
    _getPageContext() {
        const controller = this.action.currentController;
        if (!controller?.props) return {};

        const resModel = controller.props.resModel;
        const resId = controller.props.resId;
        if (!resModel) return {};

        return resId ? { model: resModel, res_id: resId } : { model: resModel };
    }

    async clearChat() {
        try {
            await this.orm.call("strat.message", "clear_conversation", []);
            this.state.messages = [];
        } catch (e) {
            console.error("Strat: failed to clear messages", e);
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    // -- Markdown renderer ------------------------------------------------

    renderMarkdown(text) {
        if (!text) return "";

        // 1. Escape HTML entities (XSS safety)
        let s = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

        // 2. Bold: **text** → <strong>
        s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

        // 3. Group consecutive lines into typed blocks
        const lines = s.split("\n");
        const blocks = [];
        let cur = { type: "p", lines: [] };

        const flush = () => {
            if (cur.lines.length) blocks.push(cur);
            cur = { type: "p", lines: [] };
        };

        for (const line of lines) {
            const t = line.trim();
            if (t.startsWith("|") && t.endsWith("|")) {
                if (cur.type !== "table") {
                    flush();
                    cur.type = "table";
                }
                cur.lines.push(t);
            } else if (/^[-*]\s+/.test(t)) {
                if (cur.type !== "ul") {
                    flush();
                    cur.type = "ul";
                }
                cur.lines.push(t.replace(/^[-*]\s+/, ""));
            } else if (/^\d+\.\s+/.test(t)) {
                if (cur.type !== "ol") {
                    flush();
                    cur.type = "ol";
                }
                cur.lines.push(t.replace(/^\d+\.\s+/, ""));
            } else if (t === "") {
                flush();
            } else {
                if (cur.type !== "p") {
                    flush();
                }
                cur.lines.push(t);
            }
        }
        flush();

        // 4. Render each block
        return blocks
            .map((b) => {
                switch (b.type) {
                    case "table":
                        return this._renderTable(b.lines);
                    case "ul":
                        return this._renderList(b.lines, false);
                    case "ol":
                        return this._renderList(b.lines, true);
                    default:
                        return `<p>${b.lines.join("<br>")}</p>`;
                }
            })
            .join("");
    }

    _renderTable(lines) {
        const isSeparator = (row) => row.replace(/[|\-\s:]/g, "") === "";
        const dataRows = lines.filter((l) => !isSeparator(l));
        if (!dataRows.length) return "";

        const parseCells = (row) =>
            row
                .split("|")
                .slice(1, -1)
                .map((c) => c.trim());

        let html = '<table class="strat-table">';

        // Header row
        const headerCells = parseCells(dataRows[0]);
        html += "<thead><tr>";
        for (const cell of headerCells) html += `<th>${cell}</th>`;
        html += "</tr></thead>";

        // Data rows
        if (dataRows.length > 1) {
            html += "<tbody>";
            for (let i = 1; i < dataRows.length; i++) {
                const cells = parseCells(dataRows[i]);
                html += "<tr>";
                for (const cell of cells) html += `<td>${cell}</td>`;
                html += "</tr>";
            }
            html += "</tbody>";
        }

        html += "</table>";
        return html;
    }

    _renderList(items, ordered) {
        const tag = ordered ? "ol" : "ul";
        const itemsHtml = items.map((i) => `<li>${i}</li>`).join("");
        return `<${tag} class="strat-list">${itemsHtml}</${tag}>`;
    }
}

registry.category("main_components").add("StratChat", {
    Component: StratChat,
});
