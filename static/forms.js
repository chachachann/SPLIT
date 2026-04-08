(function () {
    function parseJsonScript(id) {
        var node = document.getElementById(id);
        if (!node) {
            return null;
        }
        try {
            return JSON.parse(node.textContent || "null");
        } catch (error) {
            return null;
        }
    }

    function buildFieldRow(field) {
        var item = document.createElement("div");
        item.className = "workflow-repeater-item";
        item.innerHTML = [
            '<div class="workflow-repeater-head">',
            '<div class="workflow-repeater-title">Field</div>',
            '<button type="button" class="workflow-danger-btn" data-remove-item>Remove</button>',
            "</div>",
            '<div class="field-grid">',
            '<label class="field"><span class="field-label">Label</span><input type="text" data-field-prop="label"></label>',
            '<label class="field"><span class="field-label">Key</span><input type="text" data-field-prop="key"></label>',
            '<label class="field"><span class="field-label">Type</span><select class="workflow-select" data-field-prop="type">',
            '<option value="short_text">Short Text</option>',
            '<option value="long_text">Long Text</option>',
            '<option value="number">Number</option>',
            '<option value="date">Date</option>',
            '<option value="dropdown">Dropdown</option>',
            '<option value="checkbox">Checkbox</option>',
            '<option value="image_upload">Image Upload</option>',
            '<option value="file_upload">File Upload</option>',
            '</select></label>',
            '<label class="field"><span class="field-label">Default</span><input type="text" data-field-prop="default_value"></label>',
            '<label class="field field-full"><span class="field-label">Help Text</span><textarea class="workflow-textarea" data-field-prop="help_text"></textarea></label>',
            '<label class="field field-full"><span class="field-label">Dropdown Options</span><textarea class="workflow-textarea" data-field-prop="options_text" placeholder="One option per line"></textarea></label>',
            '<label class="field"><span class="field-label">Min Length / Value</span><input type="text" data-field-prop="min_value"></label>',
            '<label class="field"><span class="field-label">Max Length / Value</span><input type="text" data-field-prop="max_value"></label>',
            '<label class="field field-full"><span class="field-label">Conditional Logic JSON</span><textarea class="workflow-json" data-field-prop="conditional_logic_text" placeholder=\'{"logic":"all","rules":[{"field":"sample","op":"equals","value":"yes"}]}\'></textarea></label>',
            '<label class="field"><span class="field-label">Required</span><input type="checkbox" data-field-prop="required"></label>',
            '<label class="field"><span class="field-label">Hide After Promotion</span><input type="checkbox" data-field-prop="hide_on_promotion"></label>',
            "</div>"
        ].join("");

        item.querySelector('[data-field-prop="label"]').value = field.label || "";
        item.querySelector('[data-field-prop="key"]').value = field.key || "";
        item.querySelector('[data-field-prop="type"]').value = field.type || "short_text";
        item.querySelector('[data-field-prop="default_value"]').value = field.default_value || "";
        item.querySelector('[data-field-prop="help_text"]').value = field.help_text || "";
        item.querySelector('[data-field-prop="options_text"]').value = (field.options || []).join("\n");
        item.querySelector('[data-field-prop="min_value"]').value = (field.validation && (field.validation.min_length || field.validation.min)) || "";
        item.querySelector('[data-field-prop="max_value"]').value = (field.validation && (field.validation.max_length || field.validation.max)) || "";
        item.querySelector('[data-field-prop="conditional_logic_text"]').value = field.conditional_logic ? JSON.stringify(field.conditional_logic, null, 2) : "";
        item.querySelector('[data-field-prop="required"]').checked = !!field.required;
        item.querySelector('[data-field-prop="hide_on_promotion"]').checked = !!field.hide_on_promotion;
        return item;
    }

    function buildReviewerRow(reviewer) {
        var row = document.createElement("div");
        row.className = "workflow-repeater-item";
        row.innerHTML = [
            '<div class="workflow-repeater-head">',
            '<div class="workflow-repeater-title">Reviewer</div>',
            '<button type="button" class="workflow-danger-btn" data-remove-item>Remove</button>',
            "</div>",
            '<div class="field-grid">',
            '<label class="field"><span class="field-label">Type</span><select class="workflow-select" data-reviewer-prop="type"><option value="user">User</option><option value="role">Role</option></select></label>',
            '<label class="field"><span class="field-label">Value</span><input type="text" data-reviewer-prop="value" placeholder="Username or role name"></label>',
            "</div>"
        ].join("");
        row.querySelector('[data-reviewer-prop="type"]').value = reviewer.type || "user";
        row.querySelector('[data-reviewer-prop="value"]').value = reviewer.value || "";
        return row;
    }

    function buildStageRow(stage) {
        var item = document.createElement("div");
        item.className = "workflow-repeater-item";
        item.innerHTML = [
            '<div class="workflow-repeater-head">',
            '<div class="workflow-repeater-title">Review Stage</div>',
            '<button type="button" class="workflow-danger-btn" data-remove-item>Remove</button>',
            "</div>",
            '<div class="field-grid">',
            '<label class="field"><span class="field-label">Stage Name</span><input type="text" data-stage-prop="name"></label>',
            '<label class="field"><span class="field-label">Mode</span><select class="workflow-select" data-stage-prop="mode"><option value="sequential">Sequential</option><option value="parallel">Parallel</option></select></label>',
            "</div>",
            '<div class="workflow-repeater" data-reviewer-list></div>',
            '<button type="button" class="workflow-action-btn" data-add-reviewer>Add Reviewer</button>'
        ].join("");

        item.querySelector('[data-stage-prop="name"]').value = stage.name || "";
        item.querySelector('[data-stage-prop="mode"]').value = stage.mode || "sequential";
        var reviewerList = item.querySelector("[data-reviewer-list]");
        (stage.reviewers || []).forEach(function (reviewer) {
            reviewerList.appendChild(buildReviewerRow(reviewer));
        });
        if (!reviewerList.children.length) {
            reviewerList.appendChild(buildReviewerRow({ type: "user", value: "" }));
        }
        return item;
    }

    function serializeFieldRow(item, errors) {
        var type = item.querySelector('[data-field-prop="type"]').value;
        var minValue = item.querySelector('[data-field-prop="min_value"]').value.trim();
        var maxValue = item.querySelector('[data-field-prop="max_value"]').value.trim();
        var validation = {};
        if (type === "number") {
            if (minValue) {
                validation.min = minValue;
            }
            if (maxValue) {
                validation.max = maxValue;
            }
        } else {
            if (minValue) {
                validation.min_length = minValue;
            }
            if (maxValue) {
                validation.max_length = maxValue;
            }
        }

        var conditionalText = item.querySelector('[data-field-prop="conditional_logic_text"]').value.trim();
        var conditionalLogic = null;
        if (conditionalText) {
            try {
                conditionalLogic = JSON.parse(conditionalText);
            } catch (error) {
                if (errors) {
                    errors.push((item.querySelector('[data-field-prop="label"]').value.trim() || "Field") + " has invalid conditional JSON.");
                }
                conditionalLogic = null;
            }
        }

        return {
            label: item.querySelector('[data-field-prop="label"]').value.trim(),
            key: item.querySelector('[data-field-prop="key"]').value.trim(),
            type: type,
            default_value: item.querySelector('[data-field-prop="default_value"]').value.trim(),
            help_text: item.querySelector('[data-field-prop="help_text"]').value.trim(),
            options: item.querySelector('[data-field-prop="options_text"]').value.split(/\r?\n/).map(function (value) {
                return value.trim();
            }).filter(Boolean),
            validation: validation,
            conditional_logic: conditionalLogic,
            required: item.querySelector('[data-field-prop="required"]').checked,
            hide_on_promotion: item.querySelector('[data-field-prop="hide_on_promotion"]').checked
        };
    }

    function serializeStageRow(item) {
        var reviewers = Array.prototype.slice.call(item.querySelectorAll("[data-reviewer-list] .workflow-repeater-item")).map(function (reviewerItem) {
            return {
                type: reviewerItem.querySelector('[data-reviewer-prop="type"]').value,
                value: reviewerItem.querySelector('[data-reviewer-prop="value"]').value.trim()
            };
        }).filter(function (reviewer) {
            return reviewer.value;
        });
        return {
            name: item.querySelector('[data-stage-prop="name"]').value.trim(),
            mode: item.querySelector('[data-stage-prop="mode"]').value,
            reviewers: reviewers
        };
    }

    function setupBuilder() {
        var root = document.querySelector("[data-form-builder]");
        if (!root) {
            return;
        }
        var schemaField = root.querySelector('[name="schema_json"]');
        var stagesField = root.querySelector('[name="review_stages_json"]');
        var fieldList = root.querySelector("[data-field-list]");
        var stageList = root.querySelector("[data-stage-list]");
        var errorBox = root.querySelector("[data-builder-error]");
        var initialSchema = parseJsonScript("initial-form-schema") || [];
        var initialStages = parseJsonScript("initial-review-stages") || [];

        function syncHiddenFields() {
            var errors = [];
            schemaField.value = JSON.stringify(Array.prototype.slice.call(fieldList.children).map(function (item) {
                return serializeFieldRow(item, errors);
            }));
            stagesField.value = JSON.stringify(Array.prototype.slice.call(stageList.children).map(serializeStageRow));
            if (errorBox) {
                if (errors.length) {
                    errorBox.hidden = false;
                    errorBox.textContent = errors.join(" ");
                } else {
                    errorBox.hidden = true;
                    errorBox.textContent = "";
                }
            }
            root.dataset.builderValid = errors.length ? "false" : "true";
        }

        function bindRepeater(container, nestedReviewer) {
            container.addEventListener("click", function (event) {
                var removeButton = event.target.closest("[data-remove-item]");
                if (removeButton) {
                    var item = removeButton.closest(".workflow-repeater-item");
                    if (item) {
                        item.remove();
                        syncHiddenFields();
                    }
                    return;
                }
                if (nestedReviewer && event.target.closest("[data-add-reviewer]")) {
                    container.querySelector("[data-reviewer-list]").appendChild(buildReviewerRow({ type: "user", value: "" }));
                    syncHiddenFields();
                }
            });
            container.addEventListener("input", syncHiddenFields);
            container.addEventListener("change", syncHiddenFields);
        }

        initialSchema.forEach(function (field) {
            fieldList.appendChild(buildFieldRow(field));
        });
        if (!fieldList.children.length) {
            fieldList.appendChild(buildFieldRow({ type: "short_text" }));
        }

        initialStages.forEach(function (stage) {
            stageList.appendChild(buildStageRow(stage));
        });
        if (!stageList.children.length) {
            stageList.appendChild(buildStageRow({ mode: "sequential", reviewers: [{ type: "role", value: "Admin" }] }));
        }

        bindRepeater(fieldList, false);
        bindRepeater(stageList, true);

        var addFieldButton = root.querySelector("[data-add-field]");
        if (addFieldButton) {
            addFieldButton.addEventListener("click", function () {
                fieldList.appendChild(buildFieldRow({ type: "short_text" }));
                syncHiddenFields();
            });
        }
        var addStageButton = root.querySelector("[data-add-stage]");
        if (addStageButton) {
            addStageButton.addEventListener("click", function () {
                stageList.appendChild(buildStageRow({ mode: "sequential", reviewers: [{ type: "user", value: "" }] }));
                syncHiddenFields();
            });
        }

        root.addEventListener("submit", function (event) {
            syncHiddenFields();
            if (root.dataset.builderValid === "false") {
                event.preventDefault();
                window.alert("Fix the invalid conditional JSON before saving this form.");
            }
        });

        syncHiddenFields();
    }

    function evaluateSingleRule(rule, values) {
        var actual = values[rule.field] || "";
        var expected = rule.value;
        if (rule.op === "equals") {
            return String(actual) === String(expected);
        }
        if (rule.op === "not_equals") {
            return String(actual) !== String(expected);
        }
        if (rule.op === "contains") {
            return String(actual).indexOf(String(expected)) >= 0;
        }
        if (rule.op === "greater_than") {
            return Number(actual || 0) > Number(expected || 0);
        }
        if (rule.op === "less_than") {
            return Number(actual || 0) < Number(expected || 0);
        }
        if (rule.op === "is_empty") {
            return actual === "" || actual === null || actual === undefined;
        }
        return false;
    }

    function evaluateGroup(group, values) {
        if (!group || !group.rules || !group.rules.length) {
            return true;
        }
        var results = group.rules.map(function (rule) {
            if (rule.rules) {
                return evaluateGroup(rule, values);
            }
            return evaluateSingleRule(rule, values);
        });
        return (group.logic || "all") === "any"
            ? results.some(Boolean)
            : results.every(Boolean);
    }

    function setupConditionalFields() {
        var form = document.querySelector("[data-workflow-edit-form]");
        if (!form) {
            return;
        }
        var schema = parseJsonScript("workflow-edit-schema") || [];
        if (!schema.length) {
            return;
        }

        function currentValues() {
            var values = {};
            schema.forEach(function (field) {
                var input = form.querySelector('[name="field__' + field.key + '"]');
                if (!input) {
                    values[field.key] = "";
                    return;
                }
                if (input.type === "checkbox") {
                    values[field.key] = input.checked;
                } else {
                    values[field.key] = input.value;
                }
            });
            return values;
        }

        function renderVisibility() {
            var values = currentValues();
            schema.forEach(function (field) {
                var block = form.querySelector('[data-field-key="' + field.key + '"]');
                if (!block) {
                    return;
                }
                var visible = evaluateGroup(field.conditional_logic, values);
                block.hidden = !visible;
            });
        }

        form.addEventListener("input", renderVisibility);
        form.addEventListener("change", renderVisibility);
        renderVisibility();
    }

    function setupAutosave() {
        var form = document.querySelector("[data-workflow-edit-form]");
        if (!form || !form.dataset.autosaveUrl) {
            return;
        }
        var statusNode = document.querySelector("[data-autosave-status]");
        var timeoutId = null;

        function fieldValues() {
            var values = {};
            Array.prototype.slice.call(form.querySelectorAll("[name^='field__']")).forEach(function (input) {
                var key = input.name.replace("field__", "");
                if (input.type === "checkbox") {
                    values[key] = input.checked;
                } else {
                    values[key] = input.value;
                }
            });
            return values;
        }

        function setStatus(text) {
            if (statusNode) {
                statusNode.textContent = text;
            }
        }

        function autosave() {
            fetch(form.dataset.autosaveUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ fields: fieldValues() })
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error("Autosave failed.");
                }
                return response.json();
            }).then(function (payload) {
                setStatus(payload.updated_at ? "Autosaved " + payload.updated_at : "Autosaved");
            }).catch(function () {
                setStatus("Autosave failed");
            });
        }

        function queueAutosave() {
            window.clearTimeout(timeoutId);
            setStatus("Saving...");
            timeoutId = window.setTimeout(autosave, 800);
        }

        form.addEventListener("input", function (event) {
            if (event.target.type === "file") {
                return;
            }
            queueAutosave();
        });
        form.addEventListener("change", function (event) {
            if (event.target.type === "file") {
                return;
            }
            queueAutosave();
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        setupBuilder();
        setupConditionalFields();
        setupAutosave();
    });
})();
