/** @odoo-module */
import { Component, useState, useRef, onPatched, onWillStart } from "@odoo/owl";
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
            // MCP config state
            showSetup: false,
            mcpConfig: {
                configured: false,
                odoo_user: "",
                odoo_password: "",
                odoo_url: "",
                odoo_db: "",
                odoo_yolo: "read",
            },
            setupUser: "",
            setupPassword: "",
            setupError: "",
            setupSaving: false,
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
        if (this.state.isOpen) {
            // Load config to determine if setup is needed
            await this._loadConfig();
            if (this.state.mcpConfig.configured && !this.state.messages.length) {
                await this.loadMessages();
            }
        }
    }

    async _loadConfig() {
        try {
            const config = await this.orm.call("strat.message", "get_mcp_config", []);
            this.state.mcpConfig = config;
            this.state.showSetup = !config.configured;
            // Pre-fill form with current values
            if (config.odoo_user) {
                this.state.setupUser = config.odoo_user;
            }
            if (config.odoo_password) {
                this.state.setupPassword = config.odoo_password;
            }
        } catch (e) {
            console.error("Strat: failed to load config", e);
        }
    }

    async saveConfig() {
        const username = this.state.setupUser.trim();
        const password = this.state.setupPassword.trim();
        if (!username || !password) {
            this.state.setupError = "Username and password are required.";
            return;
        }

        this.state.setupSaving = true;
        this.state.setupError = "";

        try {
            const result = await this.orm.call("strat.message", "save_mcp_config", [], {
                username,
                password,
            });

            if (result.success) {
                this.state.mcpConfig = {
                    ...result.config,
                    configured: true,
                };
                this.state.showSetup = false;
            } else {
                this.state.setupError =
                    result.error || "Connection failed. Please check your credentials.";
            }
        } catch (error) {
            this.state.setupError =
                "Failed to save configuration: " + (error.message || error);
        }

        this.state.setupSaving = false;
    }

    showSettings() {
        this.state.setupUser = this.state.mcpConfig.odoo_user;
        this.state.setupPassword = this.state.mcpConfig.odoo_password;
        this.state.setupError = "";
        this.state.showSetup = true;
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
     * For regular data changes (create/write/delete) a soft reload via
     * ``action.restore()`` is enough — it re-renders the controller with
     * fresh data but keeps the same view architecture.
     *
     * For module-link creations the view arch itself has changed (new notebook
     * page injected), so we need a full page reload to pick up the new fields.
     */
    _reloadAffectedViews(changes) {
        const controller = this.action.currentController;
        if (!controller) return;

        const currentModel = controller.props?.resModel;
        if (!currentModel) return;

        // If a strat.module.link was created, do a full page reload — the
        // view architecture has changed and a soft reload won't pick it up.
        const linkCreated = changes.some(
            (c) => c.model === "strat.module.link" && c.action === "create",
        );
        if (linkCreated) {
            // Small delay so the user sees the agent's confirmation message
            setTimeout(() => window.location.reload(), 800);
            return;
        }

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
