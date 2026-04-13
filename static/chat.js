(function () {
    function createNode(tagName, className, textContent) {
        var node = document.createElement(tagName);
        if (className) {
            node.className = className;
        }
        if (typeof textContent === "string") {
            node.textContent = textContent;
        }
        return node;
    }

    function getInitials(value, fallback) {
        var words = String(value || "").trim().split(/\s+/).filter(Boolean);
        if (!words.length) {
            return fallback || "?";
        }
        if (words.length === 1) {
            return words[0].slice(0, 2).toUpperCase();
        }
        return (words[0][0] + words[1][0]).toUpperCase();
    }

    function applyAvatarFace(node, avatarUrl, fallbackText) {
        var fallbackNode = createNode("span", "chat-avatar-fallback", fallbackText || "?");
        if (avatarUrl) {
            var imageNode = createNode("img", "chat-avatar-image");
            imageNode.src = avatarUrl;
            imageNode.alt = "";
            imageNode.loading = "lazy";
            node.appendChild(imageNode);
            node.classList.add("has-image");
        } else {
            node.classList.remove("has-image");
        }
        node.appendChild(fallbackNode);
        return fallbackNode;
    }

    function getChannelBadge(target) {
        var match = String(target || "").match(/channel:(\d+)/);
        return match ? match[1] : "#";
    }

    function buildHandle(username) {
        var cleanUsername = String(username || "").trim();
        return cleanUsername ? "@" + cleanUsername : "";
    }

    function joinBits(values) {
        return values.filter(Boolean).join(" | ");
    }

    function normalizeSearch(value) {
        return String(value || "").trim().toLowerCase();
    }

    function parseTimestamp(value) {
        var match = String(value || "").match(
            /^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/
        );
        if (!match) {
            return null;
        }
        return new Date(
            Number(match[1]),
            Number(match[2]) - 1,
            Number(match[3]),
            Number(match[4] || 0),
            Number(match[5] || 0),
            Number(match[6] || 0)
        );
    }

    function isSameCalendarDay(left, right) {
        return !!(
            left &&
            right &&
            left.getFullYear() === right.getFullYear() &&
            left.getMonth() === right.getMonth() &&
            left.getDate() === right.getDate()
        );
    }

    function formatTimeOnly(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return value || "";
        }
        return date.toLocaleTimeString(undefined, {
            hour: "numeric",
            minute: "2-digit"
        });
    }

    function getDateKey(value) {
        var match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
        return match ? match[1] : "";
    }

    function formatDateDivider(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return "Messages";
        }

        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var yesterday = new Date(today);
        yesterday.setDate(today.getDate() - 1);

        if (date.getTime() === today.getTime()) {
            return "Today";
        }
        if (date.getTime() === yesterday.getTime()) {
            return "Yesterday";
        }

        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric"
        });
    }

    function formatConversationTime(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return "";
        }

        var now = new Date();
        var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        var yesterday = new Date(today);
        yesterday.setDate(today.getDate() - 1);
        var compareDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

        if (compareDate.getTime() === today.getTime()) {
            return formatTimeOnly(value);
        }
        if (compareDate.getTime() === yesterday.getTime()) {
            return "Yesterday";
        }
        if (date.getFullYear() === now.getFullYear()) {
            return date.toLocaleDateString(undefined, {
                month: "short",
                day: "numeric"
            });
        }

        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric"
        });
    }

    function formatLastActivity(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return "";
        }

        var now = new Date();
        var diffMinutes = Math.max(0, Math.round((now.getTime() - date.getTime()) / 60000));

        if (diffMinutes < 1) {
            return "Just now";
        }
        if (diffMinutes < 60) {
            return diffMinutes + "m ago";
        }
        if (diffMinutes < 24 * 60 && isSameCalendarDay(now, date)) {
            return "Today at " + formatTimeOnly(value);
        }

        var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        yesterday.setDate(yesterday.getDate() - 1);
        if (isSameCalendarDay(yesterday, date)) {
            return "Yesterday at " + formatTimeOnly(value);
        }

        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric"
        }) + " at " + formatTimeOnly(value);
    }

    function formatSyncLabel(syncState, lastSyncAt) {
        if (syncState === "syncing") {
            return "Syncing...";
        }
        if (syncState === "error") {
            return "Sync issue";
        }
        if (!lastSyncAt) {
            return "Waiting for sync";
        }

        var diffSeconds = Math.max(0, Math.round((Date.now() - lastSyncAt) / 1000));
        if (diffSeconds < 8) {
            return "Updated just now";
        }
        if (diffSeconds < 60) {
            return "Updated " + diffSeconds + "s ago";
        }

        var diffMinutes = Math.round(diffSeconds / 60);
        if (diffMinutes < 60) {
            return "Updated " + diffMinutes + "m ago";
        }

        return "Updated at " + new Date(lastSyncAt).toLocaleTimeString(undefined, {
            hour: "numeric",
            minute: "2-digit"
        });
    }

    function canGroupMessages(previousMessage, nextMessage) {
        if (!previousMessage || !nextMessage) {
            return false;
        }
        if (String(previousMessage.sender_username || "").toLowerCase() !== String(nextMessage.sender_username || "").toLowerCase()) {
            return false;
        }

        var previousDate = parseTimestamp(previousMessage.created_at);
        var nextDate = parseTimestamp(nextMessage.created_at);
        if (!previousDate || !nextDate || !isSameCalendarDay(previousDate, nextDate)) {
            return false;
        }

        return Math.abs(nextDate.getTime() - previousDate.getTime()) <= 5 * 60 * 1000;
    }

    function mergeMessages(existingMessages, incomingMessages) {
        var map = {};
        (existingMessages || []).forEach(function (message) {
            map[message.id] = message;
        });
        (incomingMessages || []).forEach(function (message) {
            map[message.id] = message;
        });

        return Object.keys(map).map(function (id) {
            return map[id];
        }).sort(function (left, right) {
            return Number(left.id) - Number(right.id);
        });
    }

    function initChatWidget(root) {
        if (!root || root.dataset.bound === "true") {
            return;
        }
        root.dataset.bound = "true";

        var mobileQuery = window.matchMedia("(max-width: 860px)");
        var maxAttachmentSizeBytes = 15 * 1024 * 1024;
        var state = {
            activeType: "",
            activeTarget: "",
            activeThread: null,
            overview: null,
            pollHandle: 0,
            chatOpen: false,
            onlineOpen: false,
            activeTab: "channels",
            panelMode: "messages",
            settingsOpen: false,
            mobileView: "browse",
            threadMessages: [],
            threadMeta: null,
            loadingOlder: false,
            searchTerm: "",
            onlineSearchTerm: "",
            filterMode: "all",
            drafts: {},
            syncState: "idle",
            lastSyncAt: 0,
            sending: false
        };

        var refs = {
            scrim: root.querySelector("[data-chat-scrim]"),
            onlineTrigger: root.querySelector("[data-online-trigger]"),
            onlineBadge: root.querySelector("[data-online-badge]"),
            onlinePanel: root.querySelector("[data-online-panel]"),
            onlineSummary: root.querySelector("[data-online-summary]"),
            onlineList: root.querySelector("[data-online-list]"),
            onlineClose: root.querySelector("[data-online-close]"),
            onlineSearch: root.querySelector("[data-online-search]"),
            chatTrigger: root.querySelector("[data-chat-trigger]"),
            chatBadge: root.querySelector("[data-chat-badge]"),
            chatPanel: root.querySelector("[data-chat-panel]"),
            chatSummary: root.querySelector("[data-chat-summary]"),
            chatStatUnread: root.querySelector("[data-chat-stat-unread]"),
            chatStatOnline: root.querySelector("[data-chat-stat-online]"),
            modeButtons: Array.prototype.slice.call(root.querySelectorAll("[data-chat-mode]")),
            chatSearch: root.querySelector("[data-chat-search]"),
            filterButtons: Array.prototype.slice.call(root.querySelectorAll("[data-chat-filter]")),
            mobileBrowse: root.querySelector("[data-chat-mobile-browse]"),
            close: root.querySelector("[data-chat-close]"),
            tabButtons: Array.prototype.slice.call(root.querySelectorAll("[data-chat-tab]")),
            tabPanes: Array.prototype.slice.call(root.querySelectorAll("[data-chat-pane]")),
            channelList: root.querySelector('[data-chat-list="channels"]'),
            roleList: root.querySelector('[data-chat-list="roles"]'),
            directList: root.querySelector('[data-chat-list="directs"]'),
            userList: root.querySelector('[data-chat-list="users"]'),
            threadAvatar: root.querySelector("[data-chat-thread-avatar]"),
            threadAvatarImage: root.querySelector("[data-chat-thread-avatar-image]"),
            threadAvatarText: root.querySelector("[data-chat-thread-avatar-text]"),
            threadAvatarStatus: root.querySelector("[data-chat-thread-avatar-status]"),
            kicker: root.querySelector("[data-chat-thread-kicker]"),
            title: root.querySelector("[data-chat-thread-title]"),
            subtitle: root.querySelector("[data-chat-thread-subtitle]"),
            threadFacts: root.querySelector("[data-chat-thread-facts]"),
            profileLink: root.querySelector("[data-chat-profile-link]"),
            refresh: root.querySelector("[data-chat-refresh]"),
            editToggle: root.querySelector("[data-chat-edit-toggle]"),
            mobileBack: root.querySelector("[data-chat-mobile-back]"),
            channelForm: root.querySelector("[data-chat-channel-form]"),
            channelRoomKey: root.querySelector("[data-chat-channel-room-key]"),
            channelTitleInput: root.querySelector("[data-chat-channel-title-input]"),
            channelDescriptionInput: root.querySelector("[data-chat-channel-description-input]"),
            editCancel: root.querySelector("[data-chat-edit-cancel]"),
            messageSummary: root.querySelector("[data-chat-message-summary]"),
            messageStatus: root.querySelector("[data-chat-message-status]"),
            syncStatus: root.querySelector("[data-chat-sync-status]"),
            loadOlder: root.querySelector("[data-chat-load-older]"),
            jumpLatest: root.querySelector("[data-chat-jump-latest]"),
            feed: root.querySelector("[data-chat-messages]"),
            compose: root.querySelector("[data-chat-compose]"),
            composeType: root.querySelector("[data-chat-compose-type]"),
            composeTarget: root.querySelector("[data-chat-compose-target]"),
            composeInput: root.querySelector("[data-chat-compose-input]"),
            composeTitle: root.querySelector("[data-chat-compose-title]"),
            composeHint: root.querySelector("[data-chat-compose-hint]"),
            fileInput: root.querySelector("[data-chat-file-input]"),
            fileTrigger: root.querySelector("[data-chat-file-trigger]"),
            fileName: root.querySelector("[data-chat-file-name]"),
            filePreview: root.querySelector("[data-chat-file-preview]"),
            fileChip: root.querySelector("[data-chat-file-chip]"),
            fileClear: root.querySelector("[data-chat-file-clear]"),
            sendButton: root.querySelector(".chat-send-btn"),
            composeStatus: root.querySelector("[data-chat-compose-status]")
        };

        refs.tabButtons.forEach(function (button) {
            var labelNode = button.querySelector(".chat-sidebar-tab-label");
            button.dataset.baseLabel = labelNode ? labelNode.textContent.trim() : button.textContent.trim();
            button._countNode = button.querySelector("[data-chat-tab-count]");
        });

        function fetchJson(url, options) {
            var requestOptions = options || {};
            requestOptions.headers = requestOptions.headers || {};
            requestOptions.headers["X-Requested-With"] = "XMLHttpRequest";
            return fetch(url, requestOptions).then(function (response) {
                return response.json().then(function (payload) {
                    if (!response.ok || payload.ok === false) {
                        throw new Error((payload && payload.message) || "Request failed.");
                    }
                    return payload;
                });
            });
        }

        function isMobileLayout() {
            return mobileQuery.matches;
        }

        function buildThreadKey(type, target) {
            return type && target ? type + "::" + target : "";
        }

        function getLoadedOldestId() {
            return state.threadMessages.length ? state.threadMessages[0].id : null;
        }

        function getLoadedNewestId() {
            return state.threadMessages.length ? state.threadMessages[state.threadMessages.length - 1].id : null;
        }

        function isFeedNearBottom() {
            if (!refs.feed) {
                return true;
            }
            return refs.feed.scrollHeight - refs.feed.scrollTop - refs.feed.clientHeight < 72;
        }

        function scrollFeedToBottom() {
            refs.feed.scrollTop = refs.feed.scrollHeight;
        }

        function autoResizeComposer() {
            if (!refs.composeInput) {
                return;
            }
            refs.composeInput.style.height = "auto";
            refs.composeInput.style.overflowY = "hidden";
            refs.composeInput.style.height = Math.min(refs.composeInput.scrollHeight, isMobileLayout() ? 180 : 220) + "px";
            if (refs.composeInput.scrollHeight > parseInt(refs.composeInput.style.height, 10)) {
                refs.composeInput.style.overflowY = "auto";
            }
        }

        function saveCurrentDraft() {
            var draftKey = buildThreadKey(state.activeType, state.activeTarget);
            if (!draftKey) {
                return;
            }
            state.drafts[draftKey] = refs.composeInput.value || "";
        }

        function restoreCurrentDraft() {
            var draftKey = buildThreadKey(state.activeType, state.activeTarget);
            refs.composeInput.value = draftKey && state.drafts[draftKey] ? state.drafts[draftKey] : "";
            autoResizeComposer();
        }

        function clearCurrentDraft() {
            var draftKey = buildThreadKey(state.activeType, state.activeTarget);
            if (draftKey) {
                delete state.drafts[draftKey];
            }
        }

        function renderSyncStatus() {
            if (!refs.syncStatus) {
                return;
            }
            refs.syncStatus.textContent = formatSyncLabel(state.syncState, state.lastSyncAt);
            refs.syncStatus.classList.remove("is-syncing", "is-error");
            if (state.syncState === "syncing") {
                refs.syncStatus.classList.add("is-syncing");
            } else if (state.syncState === "error") {
                refs.syncStatus.classList.add("is-error");
            }
        }

        function setSyncState(nextState) {
            state.syncState = nextState || "idle";
            if (state.syncState === "synced") {
                state.lastSyncAt = Date.now();
            }
            renderSyncStatus();
        }

        function syncScrim() {
            if (!refs.scrim) {
                return;
            }
            var shouldShow = state.chatOpen || state.onlineOpen;
            refs.scrim.setAttribute("aria-hidden", shouldShow ? "false" : "true");
            refs.scrim.classList.toggle("is-visible", shouldShow);
            document.body.classList.toggle("chat-overlay-open", shouldShow);
        }

        function syncMobileControls() {
            var mobile = isMobileLayout();
            var showThreadView = mobile && state.chatOpen && state.mobileView === "thread";
            root.classList.toggle("is-mobile-layout", mobile);
            root.classList.toggle("is-mobile-thread-view", showThreadView);
            if (refs.mobileBrowse) {
                refs.mobileBrowse.hidden = !showThreadView;
            }
            if (refs.mobileBack) {
                refs.mobileBack.hidden = !showThreadView;
            }
        }

        function setMobileView(viewName) {
            state.mobileView = viewName === "thread" ? "thread" : "browse";
            if (state.mobileView !== "thread") {
                setSettingsOpen(false);
            }
            syncMobileControls();
        }

        function setPanelMode(modeName) {
            if (modeName === "chat" || modeName === "messages" || modeName === "channels") {
                state.panelMode = modeName;
            } else {
                state.panelMode = "messages";
            }
            root.classList.toggle("is-panel-mode-chat", state.panelMode === "chat");
            root.classList.toggle("is-panel-mode-messages", state.panelMode === "messages");
            root.classList.toggle("is-panel-mode-channels", state.panelMode === "channels");
            refs.modeButtons.forEach(function (button) {
                var isActive = button.dataset.chatMode === state.panelMode;
                button.classList.toggle("is-active", isActive);
                button.setAttribute("aria-selected", isActive ? "true" : "false");
            });
        }

        function isTabAllowedForMode(tabName, modeName) {
            var mode = modeName || state.panelMode;
            if (mode === "messages") {
                return tabName === "directs" || tabName === "users";
            }
            if (mode === "channels") {
                return tabName === "channels" || tabName === "roles";
            }
            return true;
        }

        function getDefaultTabForMode(modeName) {
            if (modeName === "messages") {
                return "directs";
            }
            if (modeName === "channels") {
                return "channels";
            }
            return state.activeTab || "channels";
        }

        function ensureTabForCurrentMode() {
            if (state.panelMode === "chat") {
                return;
            }
            if (!isTabAllowedForMode(state.activeTab)) {
                setActiveTab(getDefaultTabForMode(state.panelMode));
            }
        }

        function setActiveTab(tabName) {
            state.activeTab = tabName;
            refs.tabButtons.forEach(function (button) {
                button.classList.toggle("is-active", button.dataset.chatTab === tabName);
            });
            refs.tabPanes.forEach(function (pane) {
                pane.classList.toggle("is-active", pane.dataset.chatPane === tabName);
            });
        }

        function getListForTab(tabName) {
            if (tabName === "channels") {
                return refs.channelList;
            }
            if (tabName === "roles") {
                return refs.roleList;
            }
            if (tabName === "directs") {
                return refs.directList;
            }
            if (tabName === "users") {
                return refs.userList;
            }
            return null;
        }

        function scrollTabListToTop(tabName) {
            var list = getListForTab(tabName || state.activeTab);
            if (list) {
                list.scrollTop = 0;
            }
        }

        function getTabForThread(type, preferredTab) {
            if (preferredTab) {
                return preferredTab;
            }
            if (type === "channel") {
                return "channels";
            }
            if (type === "role") {
                return "roles";
            }
            return "directs";
        }

        function setSettingsOpen(open) {
            var canEdit = !!(state.activeThread && state.activeThread.editable);
            state.settingsOpen = !!open && canEdit;
            refs.channelForm.hidden = !state.settingsOpen;
            refs.editToggle.hidden = !canEdit;
            refs.editToggle.classList.toggle("is-active", state.settingsOpen);
        }

        function pickDefaultThread(overview) {
            var collections = [
                { items: overview.direct_threads || [], tab: "directs" },
                { items: overview.role_groups || [], tab: "roles" },
                { items: overview.channels || [], tab: "channels" }
            ];

            for (var index = 0; index < collections.length; index += 1) {
                var unreadMatch = collections[index].items.find(function (item) {
                    return Number(item.unread_count || 0) > 0;
                });
                if (unreadMatch) {
                    return {
                        type: unreadMatch.thread_type,
                        target: unreadMatch.thread_type === "direct" ? unreadMatch.target_username : unreadMatch.room_key,
                        tab: collections[index].tab
                    };
                }
            }

            if (overview.channels && overview.channels.length) {
                return { type: "channel", target: overview.channels[0].room_key, tab: "channels" };
            }
            if (overview.role_groups && overview.role_groups.length) {
                return { type: "role", target: overview.role_groups[0].room_key, tab: "roles" };
            }
            if (overview.users && overview.users.length) {
                return { type: "direct", target: overview.users[0].username, tab: "users" };
            }
            return null;
        }

        function setChatOpen(open) {
            state.chatOpen = !!open;
            refs.chatPanel.setAttribute("aria-hidden", state.chatOpen ? "false" : "true");
            if (!state.chatOpen) {
                setSettingsOpen(false);
            }
            if (state.chatOpen && state.onlineOpen) {
                state.onlineOpen = false;
                refs.onlinePanel.setAttribute("aria-hidden", "true");
            }
            if (state.chatOpen) {
                if (isMobileLayout()) {
                    setMobileView(state.activeType ? state.mobileView : "browse");
                } else {
                    syncMobileControls();
                }
                setPanelMode(state.activeType ? "chat" : "messages");
                ensureTabForCurrentMode();
                refreshOverview();
            } else {
                syncMobileControls();
            }
            syncScrim();

            if (state.chatOpen && !isMobileLayout() && !state.activeType && state.overview) {
                var firstItem = pickDefaultThread(state.overview);
                if (firstItem) {
                    setActiveTab(getTabForThread(firstItem.type, firstItem.tab));
                    loadThread(firstItem.type, firstItem.target, {
                        scrollToBottom: true,
                        tab: firstItem.tab,
                        switchMobileView: false,
                        mode: "replace"
                    }).catch(function () {
                        return;
                    });
                }
            }
        }

        function setOnlineOpen(open) {
            state.onlineOpen = !!open;
            refs.onlinePanel.setAttribute("aria-hidden", state.onlineOpen ? "false" : "true");
            if (state.onlineOpen && state.chatOpen) {
                state.chatOpen = false;
                refs.chatPanel.setAttribute("aria-hidden", "true");
                setSettingsOpen(false);
            }
            if (state.onlineOpen) {
                if (refs.onlineList) {
                    refs.onlineList.scrollTop = 0;
                }
                if (refs.onlinePanel) {
                    refs.onlinePanel.scrollTop = 0;
                }
                refreshOverview();
                if (refs.onlineSearch && !isMobileLayout()) {
                    refs.onlineSearch.focus();
                }
            }
            syncMobileControls();
            syncScrim();
        }

        function closePanels() {
            if (state.chatOpen) {
                state.chatOpen = false;
                refs.chatPanel.setAttribute("aria-hidden", "true");
                setSettingsOpen(false);
            }
            if (state.onlineOpen) {
                state.onlineOpen = false;
                refs.onlinePanel.setAttribute("aria-hidden", "true");
            }
            syncMobileControls();
            syncScrim();
        }

        function updateUnreadBadge(total) {
            var unread = Number(total || 0);
            refs.chatBadge.hidden = unread <= 0;
            refs.chatBadge.textContent = unread > 99 ? "99+" : String(unread);
            refs.chatSummary.textContent = unread <= 0 ? "All caught up" : (unread === 1 ? "1 unread" : String(unread) + " unread");
        }

        function updateOnlineBadge(total) {
            var online = Number(total || 0);
            refs.onlineBadge.hidden = online <= 0;
            refs.onlineBadge.textContent = online > 99 ? "99+" : String(online);
            refs.onlineSummary.textContent = online === 1 ? "1 online now" : String(online) + " online now";
        }

        function updateStatCards(overview) {
            var unreadTotal = Number((overview && overview.unread_total) || 0);
            var onlineTotal = (overview && overview.users ? overview.users.filter(function (item) {
                return item.presence === "online";
            }).length : 0);

            if (refs.chatStatUnread) {
                refs.chatStatUnread.textContent = unreadTotal > 99 ? "99+" : String(unreadTotal);
            }
            if (refs.chatStatOnline) {
                refs.chatStatOnline.textContent = onlineTotal > 99 ? "99+" : String(onlineTotal);
            }
        }

        function isItemActive(type, target) {
            return state.activeType === type && state.activeTarget === target;
        }

        function updateTabCounts(overview) {
            var counts = {
                channels: (overview.channels || []).reduce(function (sum, item) { return sum + Number(item.unread_count || 0); }, 0),
                roles: (overview.role_groups || []).reduce(function (sum, item) { return sum + Number(item.unread_count || 0); }, 0),
                directs: (overview.direct_threads || []).reduce(function (sum, item) { return sum + Number(item.unread_count || 0); }, 0),
                users: 0
            };

            refs.tabButtons.forEach(function (button) {
                var countNode = button._countNode;
                var count = counts[button.dataset.chatTab] || 0;
                if (!countNode) {
                    return;
                }
                countNode.hidden = count <= 0;
                countNode.textContent = count > 99 ? "99+" : String(count);
            });
        }

        function getSearchText(item) {
            return normalizeSearch([
                item.title,
                item.description,
                item.role_name,
                item.target_username,
                item.username,
                item.fullname,
                item.designation,
                item.last_message_preview,
                item.last_message_sender_name
            ].join(" "));
        }

        function getSearchRank(item, term) {
            var searchTerm = normalizeSearch(term);
            if (!searchTerm) {
                return 0;
            }

            var username = normalizeSearch(item.target_username || item.username);
            var primaryName = normalizeSearch(item.title || item.fullname || item.display_name);
            var secondaryName = normalizeSearch(item.fullname || item.display_name || item.title);
            var designation = normalizeSearch(item.description || item.designation || "");
            var combined = getSearchText(item);
            var compactTerm = searchTerm.replace(/\s+/g, "");
            var compactCombined = combined.replace(/\s+/g, "");
            var tokens = searchTerm.split(/\s+/).filter(Boolean);

            if (username && username === searchTerm) {
                return 0;
            }
            if (primaryName && primaryName === searchTerm) {
                return 1;
            }
            if (secondaryName && secondaryName === searchTerm) {
                return 2;
            }
            if (username && username.indexOf(searchTerm) !== -1) {
                return 10 + username.indexOf(searchTerm);
            }
            if (primaryName && primaryName.indexOf(searchTerm) !== -1) {
                return 30 + primaryName.indexOf(searchTerm);
            }
            if (secondaryName && secondaryName.indexOf(searchTerm) !== -1) {
                return 40 + secondaryName.indexOf(searchTerm);
            }
            if (designation && designation.indexOf(searchTerm) !== -1) {
                return 60 + designation.indexOf(searchTerm);
            }
            if (compactTerm && compactCombined.indexOf(compactTerm) !== -1) {
                return 80 + compactCombined.indexOf(compactTerm);
            }
            if (tokens.length && tokens.every(function (token) { return combined.indexOf(token) !== -1; })) {
                return 120 + combined.indexOf(tokens[0]);
            }
            return -1;
        }

        function sortSearchItems(items, term) {
            return (items || []).slice().sort(function (left, right) {
                var leftRank = getSearchRank(left, term);
                var rightRank = getSearchRank(right, term);
                if (leftRank !== rightRank) {
                    return leftRank - rightRank;
                }
                if (!!left.is_favorite !== !!right.is_favorite) {
                    return left.is_favorite ? -1 : 1;
                }
                return getSearchText(left).localeCompare(getSearchText(right));
            });
        }

        function filterItems(items, tabName) {
            var filteredItems = (items || []).filter(function (item) {
                if (state.searchTerm && getSearchRank(item, state.searchTerm) < 0) {
                    return false;
                }
                if (state.filterMode === "unread" && tabName !== "users") {
                    return Number(item.unread_count || 0) > 0;
                }
                return true;
            });

            if (state.searchTerm) {
                return sortSearchItems(filteredItems, state.searchTerm);
            }

            return filteredItems;
        }

        function formatPreviewLine(item) {
            var preview = item.last_message_preview || "No messages yet";
            if (!item.last_message_sender_name) {
                return preview;
            }

            if (item.thread_type === "direct") {
                return item.last_message_is_self ? "You: " + preview : preview;
            }

            return (item.last_message_is_self ? "You" : item.last_message_sender_name) + ": " + preview;
        }

        function buildListItem(config) {
            var shell = createNode("div", "chat-list-item-shell");
            var button = createNode("button", "chat-list-item");
            var actions = null;
            button.type = "button";
            button.dataset.chatType = config.type;
            button.dataset.chatTarget = config.target;
            if (isItemActive(config.type, config.target)) {
                button.classList.add("is-active");
            }
            if (config.isFavorite) {
                button.classList.add("is-favorite");
            }

            var main = createNode("div", "chat-list-item-main");
            var avatar = createNode("span", "chat-list-item-avatar" + (config.avatarTone ? " chat-list-item-avatar-" + config.avatarTone : ""));
            applyAvatarFace(avatar, config.avatarUrl, config.avatarText);
            if (config.status) {
                avatar.appendChild(createNode("span", "chat-list-item-avatar-status" + (config.status === "online" ? " is-online" : "")));
            }
            main.appendChild(avatar);

            var copy = createNode("div", "chat-list-item-copy");
            if (config.eyebrow) {
                copy.appendChild(createNode("div", "chat-list-item-eyebrow", config.eyebrow));
            }
            var titleRow = createNode("div", "chat-list-item-row");
            titleRow.appendChild(createNode("div", "chat-list-item-title", config.title));

            var tail = createNode("div", "chat-list-item-tail");
            if (config.timestamp) {
                tail.appendChild(createNode("span", "chat-list-item-time", config.timestamp));
            }
            if (config.meta) {
                tail.appendChild(createNode("span", "chat-list-item-status" + (config.metaTone ? " is-" + config.metaTone : ""), config.meta));
            }
            if (config.unreadCount > 0) {
                tail.appendChild(createNode("span", "chat-list-item-unread", String(config.unreadCount)));
            }
            if (tail.childNodes.length) {
                titleRow.appendChild(tail);
            }
            copy.appendChild(titleRow);

            if (config.subtitle) {
                copy.appendChild(createNode("div", "chat-list-item-subtitle", config.subtitle));
            }
            if (config.note) {
                copy.appendChild(createNode("div", "chat-list-item-note" + (config.unreadCount > 0 ? " is-unread" : ""), config.note));
            }

            main.appendChild(copy);
            button.appendChild(main);
            if (config.actions && config.actions.length) {
                actions = createNode("div", "chat-list-item-actions");
                config.actions.forEach(function (action) {
                    var actionButton = createNode(
                        "button",
                        "chat-list-item-action" + (action.className ? " " + action.className : ""),
                        action.label
                    );
                    actionButton.type = "button";
                    actionButton.title = action.title || action.label;
                    actionButton.setAttribute("aria-label", action.title || action.label);
                    actionButton.addEventListener("click", function (event) {
                        event.preventDefault();
                        event.stopPropagation();
                        action.onClick();
                    });
                    actions.appendChild(actionButton);
                });
            }
            button.addEventListener("click", function () {
                if (typeof button.blur === "function") {
                    button.blur();
                }
                setChatOpen(true);
                setPanelMode("chat");
                setActiveTab(getTabForThread(config.type, config.tab));
                loadThread(config.type, config.target, {
                    scrollToBottom: true,
                    tab: config.tab,
                    switchMobileView: true,
                    mode: "replace"
                }).catch(function () {
                    return;
                });
            });
            shell.appendChild(button);
            if (actions) {
                shell.appendChild(actions);
            }
            return shell;
        }

        function updateFavoriteButtonLabel(button, isActive) {
            if (!button) {
                return;
            }
            button.dataset.chatFavoriteActive = isActive ? "true" : "false";
            if (button.classList.contains("online-user-action-button")) {
                button.textContent = isActive ? "★ Favorite" : "☆ Favorite";
                button.classList.toggle("is-active", isActive);
                return;
            }
            if (button.classList.contains("chat-list-item-action-favorite")) {
                button.textContent = isActive ? "★" : "☆";
                button.classList.toggle("is-active", isActive);
                return;
            }
            button.textContent = isActive ? "Remove Favorite" : "Add to Favorites";
        }

        function syncProfileFavoriteButtons() {
            var favoriteUsernames = {};
            ((state.overview && state.overview.favorites) || []).forEach(function (item) {
                favoriteUsernames[String(item.username || "").toLowerCase()] = true;
            });

            Array.prototype.slice.call(document.querySelectorAll("[data-chat-favorite-toggle]")).forEach(function (button) {
                var targetUsername = String(button.getAttribute("data-chat-favorite-toggle") || "").trim().toLowerCase();
                updateFavoriteButtonLabel(button, !!favoriteUsernames[targetUsername]);
            });
        }

        function sendFavoriteToggle(username, shouldFavorite) {
            var favoriteToggleUrl = root.dataset.favoriteToggleUrl;
            if (!favoriteToggleUrl) {
                return Promise.reject(new Error("Favorite toggle is unavailable."));
            }
            var formData = new FormData();
            formData.append("username", username);
            formData.append("state", shouldFavorite ? "on" : "off");
            return fetchJson(favoriteToggleUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                syncOverview(payload.overview || {});
                return payload;
            });
        }

        function sendFavoriteMove(username, direction) {
            var favoriteMoveUrl = root.dataset.favoriteMoveUrl;
            if (!favoriteMoveUrl) {
                return Promise.reject(new Error("Favorite ordering is unavailable."));
            }
            var formData = new FormData();
            formData.append("username", username);
            formData.append("direction", direction);
            return fetchJson(favoriteMoveUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                syncOverview(payload.overview || {});
                return payload;
            });
        }

        function toggleFavorite(username, shouldFavorite, triggerButton) {
            if (!username) {
                return Promise.resolve();
            }
            if (triggerButton) {
                triggerButton.disabled = true;
            }
            return sendFavoriteToggle(username, shouldFavorite)
                .then(function (payload) {
                    updateFavoriteButtonLabel(triggerButton, shouldFavorite);
                    setComposeStatus(payload.message || "", "success");
                    return payload;
                })
                .catch(function (error) {
                    setComposeStatus(error.message, "error");
                    throw error;
                })
                .finally(function () {
                    if (triggerButton) {
                        triggerButton.disabled = false;
                    }
                });
        }

        function buildFavoriteActions(item, tabName) {
            if (!item || !item.username && !item.target_username) {
                return [];
            }
            var username = item.target_username || item.username;
            var actions = [
                {
                    label: item.is_favorite ? "★" : "☆",
                    title: item.is_favorite ? "Remove from favorites" : "Add to favorites",
                    className: "chat-list-item-action-favorite" + (item.is_favorite ? " is-active" : ""),
                    onClick: function () {
                        toggleFavorite(username, !item.is_favorite).catch(function () {
                            return;
                        });
                    }
                }
            ];
            if (item.is_favorite && (tabName === "directs" || tabName === "users")) {
                actions.push({
                    label: "↑",
                    title: "Move favorite up",
                    onClick: function () {
                        sendFavoriteMove(username, "up").catch(function (error) {
                            setComposeStatus(error.message, "error");
                        });
                    }
                });
                actions.push({
                    label: "↓",
                    title: "Move favorite down",
                    onClick: function () {
                        sendFavoriteMove(username, "down").catch(function (error) {
                            setComposeStatus(error.message, "error");
                        });
                    }
                });
            }
            return actions;
        }

        function openDirectConversation(username, preferredTab) {
            if (!username) {
                return Promise.resolve();
            }
            setOnlineOpen(false);
            setChatOpen(true);
            setPanelMode("chat");
            setActiveTab(preferredTab || "directs");
            return loadThread("direct", username, {
                scrollToBottom: true,
                tab: preferredTab || "directs",
                switchMobileView: true,
                mode: "replace"
            });
        }

        function renderList(container, items, builder, emptyLabel) {
            container.innerHTML = "";
            if (!items || !items.length) {
                container.appendChild(createNode("div", "chat-empty-state chat-empty-state-compact", emptyLabel || "Nothing here yet."));
                return;
            }
            items.forEach(function (item) {
                container.appendChild(builder(item));
            });
        }

        function renderOnlineUsers(overview) {
            var directoryUsers = overview.users || [];
            var onlineUsers = directoryUsers.filter(function (item) {
                return item.presence === "online";
            });
            var totalOnline = onlineUsers.length;
            if (state.onlineSearchTerm) {
                onlineUsers = sortSearchItems(
                    directoryUsers.filter(function (item) {
                        return getSearchRank(item, state.onlineSearchTerm) >= 0;
                    }),
                    state.onlineSearchTerm
                );
            }
            updateOnlineBadge(totalOnline);
            if (refs.onlineSummary) {
                if (state.onlineSearchTerm) {
                    refs.onlineSummary.textContent = onlineUsers.length + " match" + (onlineUsers.length === 1 ? "" : "es") + " across all users";
                } else {
                    refs.onlineSummary.textContent = totalOnline === 1 ? "1 online" : totalOnline + " online";
                }
            }
            refs.onlineList.innerHTML = "";
            if (!onlineUsers.length) {
                refs.onlineList.appendChild(createNode(
                    "div",
                    "chat-empty-state chat-empty-state-compact",
                    state.onlineSearchTerm ? "No users match your search." : "No online users right now."
                ));
                return;
            }

            onlineUsers.forEach(function (user) {
                var card = createNode("article", "online-user-card");
                var button = createNode("button", "online-user-item");
                button.type = "button";

                var avatar = createNode("span", "chat-list-item-avatar chat-list-item-avatar-person");
                applyAvatarFace(avatar, user.avatar_url, user.avatar_initials || getInitials(user.fullname, "U"));
                avatar.appendChild(createNode("span", "chat-list-item-avatar-status" + (user.presence === "online" ? " is-online" : "")));

                var copy = createNode("div", "online-user-copy");
                copy.appendChild(createNode("strong", "", user.fullname));
                copy.appendChild(createNode(
                    "span",
                    "",
                    joinBits([
                        buildHandle(user.username),
                        user.presence === "online"
                            ? "Online now"
                            : "Last active " + (formatLastActivity(user.last_seen_at || user.last_login_at) || "Not available")
                    ])
                ));

                button.appendChild(avatar);
                button.appendChild(copy);
                button.addEventListener("click", function () {
                    if (typeof button.blur === "function") {
                        button.blur();
                    }
                    openDirectConversation(user.username, "directs").catch(function () {
                        return;
                    });
                });
                card.appendChild(button);
                var actions = createNode("div", "online-user-actions");
                var favoriteButton = createNode(
                    "button",
                    "online-user-action online-user-action-button" + (user.is_favorite ? " is-active" : ""),
                    user.is_favorite ? "★ Favorite" : "☆ Favorite"
                );
                favoriteButton.type = "button";
                favoriteButton.addEventListener("click", function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    toggleFavorite(user.username, !user.is_favorite, favoriteButton).then(function () {
                        favoriteButton.classList.toggle("is-active", !user.is_favorite);
                    }).catch(function () {
                        return;
                    });
                });
                actions.appendChild(favoriteButton);
                if (user.profile_url) {
                    var profileLink = createNode("a", "online-user-action", "Profile");
                    profileLink.href = user.profile_url;
                    actions.appendChild(profileLink);
                }
                card.appendChild(actions);
                refs.onlineList.appendChild(card);
            });
        }

        function renderProfileSearchPanels() {
            var searchPanels = Array.prototype.slice.call(document.querySelectorAll("[data-profile-chat-search]"));
            if (!searchPanels.length) {
                return;
            }

            searchPanels.forEach(function (panel) {
                var input = panel.querySelector("[data-profile-chat-search-input]");
                var results = panel.querySelector("[data-profile-chat-search-results]");
                if (!input || !results) {
                    return;
                }

                var term = normalizeSearch(input.value);
                results.innerHTML = "";
                if (!term) {
                    results.hidden = true;
                    return;
                }

                var matches = sortSearchItems(
                    (state.overview && state.overview.users || []).filter(function (item) {
                        return getSearchRank(item, term) >= 0;
                    }),
                    term
                ).slice(0, 8);

                results.hidden = !matches.length;
                if (!matches.length) {
                    results.appendChild(createNode("div", "chat-empty-state chat-empty-state-compact", "No users match your search."));
                    results.hidden = false;
                    return;
                }

                matches.forEach(function (item) {
                    var row = createNode("div", "profile-chat-search-row");
                    var identity = createNode("button", "profile-chat-search-user");
                    identity.type = "button";
                    identity.appendChild(createNode("strong", "", item.fullname));
                    identity.appendChild(createNode("span", "", joinBits([buildHandle(item.username), item.designation])));
                    identity.addEventListener("click", function () {
                        openDirectConversation(item.username, "directs").catch(function (error) {
                            setComposeStatus(error.message, "error");
                        });
                    });
                    row.appendChild(identity);

                    var favoriteButton = createNode(
                        "button",
                        "chat-list-item-action chat-list-item-action-favorite" + (item.is_favorite ? " is-active" : ""),
                        item.is_favorite ? "★" : "☆"
                    );
                    favoriteButton.type = "button";
                    favoriteButton.addEventListener("click", function () {
                        toggleFavorite(item.username, !item.is_favorite, favoriteButton).catch(function () {
                            return;
                        });
                    });
                    row.appendChild(favoriteButton);
                    results.appendChild(row);
                });
            });
        }

        function getEmptyListLabel(tabName) {
            if (state.searchTerm) {
                return "No conversations match your search.";
            }
            if (state.filterMode === "unread" && tabName !== "users") {
                return "No unread conversations in this section.";
            }
            if (tabName === "channels") {
                return "No channels available.";
            }
            if (tabName === "roles") {
                return "No role groups available.";
            }
            if (tabName === "directs") {
                return "No direct conversations yet.";
            }
            return "No other users found.";
        }

        function findOverviewThread(type, target) {
            if (!state.overview) {
                return null;
            }
            if (type === "channel") {
                return (state.overview.channels || []).find(function (item) {
                    return item.room_key === target;
                }) || null;
            }
            if (type === "role") {
                return (state.overview.role_groups || []).find(function (item) {
                    return item.room_key === target;
                }) || null;
            }
            if (type === "direct") {
                return (state.overview.direct_threads || []).find(function (item) {
                    return item.target_username === target;
                }) || null;
            }
            return null;
        }

        function syncActiveThreadFromOverview() {
            if (!state.activeThread || !state.activeType || !state.activeTarget) {
                return;
            }

            var match = findOverviewThread(state.activeType, state.activeTarget);
            if (!match) {
                return;
            }

            state.activeThread.member_count = match.member_count || state.activeThread.member_count || 0;
            if (state.activeType === "direct") {
                state.activeThread.title = match.title || state.activeThread.title;
                state.activeThread.description = match.description || state.activeThread.description;
                state.activeThread.target_username = match.target_username || state.activeThread.target_username;
                state.activeThread.avatar_url = match.avatar_url || state.activeThread.avatar_url || "";
                state.activeThread.profile_url = match.profile_url || state.activeThread.profile_url || "";
                state.activeThread.presence = {
                    status: match.presence,
                    status_label: match.presence_label,
                    is_online: match.presence === "online",
                    last_seen_at: match.last_seen_at,
                    last_login_at: match.last_login_at
                };
            }

            applyThreadHeader(state.activeThread);
        }

        function syncOverview(overview) {
            state.overview = overview || {
                channels: [],
                role_groups: [],
                direct_threads: [],
                users: [],
                unread_total: 0
            };

            updateUnreadBadge(state.overview.unread_total);
            updateStatCards(state.overview);
            updateTabCounts(state.overview);
            renderOnlineUsers(state.overview);
            syncProfileFavoriteButtons();
            renderProfileSearchPanels();

            renderList(refs.channelList, filterItems(state.overview.channels, "channels"), function (item) {
                return buildListItem({
                    type: "channel",
                    tab: "channels",
                    target: item.room_key,
                    title: item.title,
                    subtitle: item.description || "Public room",
                    note: formatPreviewLine(item),
                    unreadCount: item.unread_count || 0,
                    timestamp: formatConversationTime(item.last_message_at),
                    eyebrow: joinBits(["Channel " + getChannelBadge(item.room_key), item.member_count ? item.member_count + " members" : "Public room"]),
                    avatarText: getChannelBadge(item.room_key),
                    avatarTone: "channel"
                });
            }, getEmptyListLabel("channels"));

            renderList(refs.roleList, filterItems(state.overview.role_groups, "roles"), function (item) {
                return buildListItem({
                    type: "role",
                    tab: "roles",
                    target: item.room_key,
                    title: item.title,
                    subtitle: item.description || (item.role_name ? item.role_name + " group" : "Role-based room"),
                    note: formatPreviewLine(item),
                    unreadCount: item.unread_count || 0,
                    timestamp: formatConversationTime(item.last_message_at),
                    eyebrow: joinBits([item.role_name || "Role room", item.member_count ? item.member_count + " members" : "Restricted"]),
                    avatarText: getInitials(item.role_name || item.title, "RG"),
                    avatarTone: "role"
                });
            }, getEmptyListLabel("roles"));

            renderList(refs.directList, filterItems(state.overview.direct_threads, "directs"), function (item) {
                return buildListItem({
                    type: "direct",
                    tab: "directs",
                    target: item.target_username,
                    title: item.title,
                    subtitle: joinBits([item.description, buildHandle(item.target_username)]),
                    note: formatPreviewLine(item),
                    unreadCount: item.unread_count || 0,
                    timestamp: formatConversationTime(item.last_message_at),
                    meta: item.presence === "online" ? "Online" : "Offline",
                    metaTone: item.presence || "offline",
                    status: item.presence,
                    eyebrow: joinBits([
                        item.is_favorite ? "Pinned favorite" : "",
                        item.presence === "online"
                            ? "Online now"
                            : "Last active " + (formatLastActivity(item.last_seen_at || item.last_login_at) || "Not available")
                    ]),
                    avatarText: getInitials(item.title, "DM"),
                    avatarUrl: item.avatar_url,
                    avatarTone: "direct",
                    isFavorite: item.is_favorite,
                    actions: buildFavoriteActions(item, "directs")
                });
            }, getEmptyListLabel("directs"));

            renderList(refs.userList, filterItems(state.overview.users, "users"), function (item) {
                var presenceNote = item.presence === "online"
                    ? "Currently online"
                    : "Last active " + (formatLastActivity(item.last_seen_at || item.last_login_at) || "Not available");
                return buildListItem({
                    type: "direct",
                    tab: "users",
                    target: item.username,
                    title: item.fullname,
                    subtitle: joinBits([item.designation, buildHandle(item.username)]),
                    note: presenceNote,
                    unreadCount: 0,
                    meta: item.presence_label || "Offline",
                    metaTone: item.presence || "offline",
                    status: item.presence,
                    eyebrow: item.is_favorite ? "Pinned favorite" : "Start a direct chat",
                    avatarText: getInitials(item.fullname, "U"),
                    avatarUrl: item.avatar_url,
                    avatarTone: "person",
                    isFavorite: item.is_favorite,
                    actions: buildFavoriteActions(item, "users")
                });
            }, getEmptyListLabel("users"));

            syncActiveThreadFromOverview();
        }

        function updateThreadTools() {
            var totalCount = Number(state.threadMeta && state.threadMeta.total_count || 0);
            var loadedCount = state.threadMessages.length;
            var remainingCount = state.threadMeta && state.threadMeta.has_more_before ? Math.max(totalCount - loadedCount, 0) : 0;

            if (!state.activeThread) {
                refs.messageSummary.textContent = "No conversation selected";
                refs.messageStatus.textContent = "Open a channel, role room, or direct message to view history.";
                refs.loadOlder.hidden = true;
                refs.jumpLatest.hidden = true;
                return;
            }

            if (!loadedCount && !totalCount) {
                refs.messageSummary.textContent = "No messages yet";
                refs.messageStatus.textContent = "Send the first message in this conversation.";
                refs.loadOlder.hidden = true;
                refs.jumpLatest.hidden = true;
                return;
            }

            if (remainingCount > 0) {
                refs.messageSummary.textContent = "Showing " + loadedCount + " of " + totalCount + " messages";
                refs.messageStatus.textContent = state.loadingOlder ? "Loading older messages..." : remainingCount + " older messages are not loaded yet.";
            } else {
                refs.messageSummary.textContent = totalCount === 1 ? "1 message" : totalCount + " messages";
                refs.messageStatus.textContent = "You are viewing the full conversation.";
            }

            refs.loadOlder.hidden = !state.threadMeta || !state.threadMeta.has_more_before;
            refs.loadOlder.disabled = state.loadingOlder;
            refs.loadOlder.textContent = state.loadingOlder ? "Loading..." : (remainingCount > 0 ? "Load Older (" + remainingCount + ")" : "Load Older");
        }

        function syncJumpLatestVisibility() {
            refs.jumpLatest.hidden = !state.activeThread || !state.threadMessages.length || isFeedNearBottom();
        }

        function buildFactNode(label, tone) {
            return createNode("span", "chat-thread-fact" + (tone ? " is-" + tone : ""), label);
        }

        function renderThreadFacts(thread) {
            if (!refs.threadFacts) {
                return;
            }
            refs.threadFacts.innerHTML = "";
            if (!thread) {
                return;
            }

            if (thread.thread_type === "direct") {
                if (thread.target_username) {
                    refs.threadFacts.appendChild(buildFactNode(buildHandle(thread.target_username), "soft"));
                }
                if (thread.presence && thread.presence.status_label) {
                    refs.threadFacts.appendChild(
                        buildFactNode(
                            thread.presence.status_label,
                            thread.presence.status === "online" ? "online" : "offline"
                        )
                    );
                }
                refs.threadFacts.appendChild(buildFactNode("2 participants", "soft"));
                return;
            }

            if (thread.member_count) {
                refs.threadFacts.appendChild(
                    buildFactNode(
                        thread.member_count + (thread.member_count === 1 ? " member" : " members"),
                        "soft"
                    )
                );
            }
            if (thread.thread_type === "channel") {
                refs.threadFacts.appendChild(buildFactNode("Channel " + getChannelBadge(thread.room_key), "channel"));
            } else if (thread.thread_type === "role") {
                refs.threadFacts.appendChild(buildFactNode("Role room", "role"));
            }
        }

        function updateComposerAvailability() {
            var hasThread = !!state.activeThread;
            refs.compose.classList.toggle("is-disabled", !hasThread);
            refs.composeInput.disabled = !hasThread || state.sending;
            refs.fileInput.disabled = !hasThread || state.sending;
            if (refs.sendButton) {
                refs.sendButton.disabled = !hasThread || state.sending;
                refs.sendButton.textContent = state.sending ? "Sending..." : "Send";
            }
            if (refs.fileTrigger) {
                refs.fileTrigger.classList.toggle("is-disabled", !hasThread || state.sending);
            }
            refs.composeInput.placeholder = hasThread ? "Write a message..." : "Select a conversation first.";
        }

        function applyThreadHeader(thread) {
            if (!thread) {
                refs.kicker.textContent = "Conversation";
                refs.title.textContent = "Select a conversation";
                refs.subtitle.textContent = "Open a channel, role room, or direct message.";
                refs.threadAvatar.className = "chat-thread-avatar";
                refs.threadAvatarText.textContent = "?";
                if (refs.threadAvatarImage) {
                    refs.threadAvatarImage.hidden = true;
                    refs.threadAvatarImage.removeAttribute("src");
                }
                refs.threadAvatarStatus.hidden = true;
                if (refs.profileLink) {
                    refs.profileLink.hidden = true;
                    refs.profileLink.removeAttribute("href");
                }
                renderThreadFacts(null);
                refs.composeType.value = "";
                refs.composeTarget.value = "";
                refs.composeTitle.textContent = "Message composer";
                refs.composeHint.textContent = "Select a conversation to start messaging.";
                refs.composeInput.value = "";
                autoResizeComposer();
                setSettingsOpen(false);
                updateComposerAvailability();
                updateThreadTools();
                return;
            }

            refs.title.textContent = thread.title || "Conversation";

            var kicker = "Conversation";
            var subtitle = thread.description || "";
            var avatarText = "?";
            var avatarUrl = "";
            var avatarTone = "direct";
            var directStatus = "";

            if (thread.thread_type === "channel") {
                kicker = "Channel";
                subtitle = thread.description || "Public room";
                avatarText = getChannelBadge(thread.room_key);
                avatarTone = "channel";
            } else if (thread.thread_type === "role") {
                kicker = "Role Group";
                subtitle = thread.description || "Role-based room";
                avatarText = getInitials(thread.title, "RG");
                avatarTone = "role";
            } else if (thread.thread_type === "direct") {
                kicker = "Direct Message";
                subtitle = joinBits([
                    thread.description,
                    buildHandle(thread.target_username),
                    thread.presence && thread.presence.is_online
                        ? "Online now"
                        : (thread.presence && (thread.presence.last_seen_at || thread.presence.last_login_at)
                            ? "Last active " + formatLastActivity(thread.presence.last_seen_at || thread.presence.last_login_at)
                            : "")
                ]);
                avatarText = getInitials(thread.title, "DM");
                avatarUrl = thread.avatar_url || "";
                avatarTone = "direct";
                directStatus = thread.presence ? thread.presence.status : "";
            }

            refs.kicker.textContent = kicker;
            refs.subtitle.textContent = subtitle || "Conversation ready.";
            refs.threadAvatar.className = "chat-thread-avatar chat-thread-avatar-" + avatarTone;
            refs.threadAvatarText.textContent = avatarText;
            if (refs.threadAvatarImage) {
                if (avatarUrl) {
                    refs.threadAvatarImage.src = avatarUrl;
                    refs.threadAvatarImage.hidden = false;
                    refs.threadAvatar.classList.add("has-image");
                } else {
                    refs.threadAvatarImage.hidden = true;
                    refs.threadAvatarImage.removeAttribute("src");
                    refs.threadAvatar.classList.remove("has-image");
                }
            }
            refs.threadAvatarStatus.hidden = !directStatus;
            refs.threadAvatarStatus.classList.toggle("is-online", directStatus === "online");
            if (refs.profileLink) {
                refs.profileLink.hidden = thread.thread_type !== "direct" || !thread.profile_url;
                if (thread.thread_type === "direct" && thread.profile_url) {
                    refs.profileLink.href = thread.profile_url;
                } else {
                    refs.profileLink.removeAttribute("href");
                }
            }
            refs.channelRoomKey.value = thread.editable ? thread.room_key : "";
            refs.channelTitleInput.value = thread.editable ? (thread.title || "") : "";
            refs.channelDescriptionInput.value = thread.editable ? (thread.description || "") : "";
            refs.composeType.value = thread.thread_type;
            refs.composeTarget.value = thread.thread_type === "direct" ? thread.target_username : thread.room_key;
            refs.composeTitle.textContent = "Message " + (thread.title || "conversation");
            refs.composeHint.textContent = isMobileLayout()
                ? "Tap send to reply. Attachments up to 15 MB."
                : "Enter to send. Shift+Enter for a line break. Attachments up to 15 MB.";

            renderThreadFacts(thread);
            setSettingsOpen(false);
            restoreCurrentDraft();
            updateComposerAvailability();
            syncMobileControls();
            updateThreadTools();
        }

        function buildAttachmentNode(attachment) {
            var attachmentNode = createNode("div", "chat-attachment");
            var attachmentLink = createNode("a", "chat-attachment-link");
            attachmentLink.href = attachment.url;
            attachmentLink.target = "_blank";
            attachmentLink.rel = "noopener noreferrer";

            var attachmentCopy = createNode("span", "chat-attachment-link-copy");
            attachmentCopy.appendChild(createNode(
                "span",
                "chat-attachment-kind",
                attachment.kind === "image" ? "Image" : "File"
            ));
            attachmentCopy.appendChild(createNode("span", "chat-attachment-name", attachment.name));
            attachmentLink.appendChild(attachmentCopy);
            attachmentNode.appendChild(attachmentLink);

            if (attachment.kind === "image") {
                var imageLink = createNode("a", "chat-attachment-preview");
                imageLink.href = attachment.url;
                imageLink.target = "_blank";
                imageLink.rel = "noopener noreferrer";
                var image = createNode("img");
                image.src = attachment.url;
                image.alt = attachment.name;
                image.loading = "lazy";
                imageLink.appendChild(image);
                attachmentNode.appendChild(imageLink);
            }

            return attachmentNode;
        }

        function buildMessageNode(thread, message, options) {
            var layout = options || {};
            var showAuthor = thread.thread_type !== "direct" && !message.is_self && !layout.continuesFromPrevious;
            var shell = createNode(
                "div",
                "chat-message-shell" +
                    (message.is_self ? " is-self" : "") +
                    (layout.continuesFromPrevious ? " is-continued" : "")
            );

            if (!message.is_self) {
                var avatarNode;
                shell.appendChild(
                    layout.showAvatar
                        ? (function () {
                            avatarNode = createNode(message.sender_profile_url ? "a" : "span", "chat-message-avatar");
                            if (message.sender_profile_url) {
                                avatarNode.href = message.sender_profile_url;
                            }
                            applyAvatarFace(
                                avatarNode,
                                message.sender_avatar_url,
                                message.sender_avatar_initials || getInitials(message.sender_fullname, "U")
                            );
                            return avatarNode;
                        })()
                        : createNode("span", "chat-message-avatar-spacer")
                );
            }

            var stack = createNode("div", "chat-message-stack");
            if (showAuthor) {
                if (message.sender_profile_url) {
                    var authorLink = createNode("a", "chat-message-author-line chat-message-author-link", message.sender_fullname);
                    authorLink.href = message.sender_profile_url;
                    stack.appendChild(authorLink);
                } else {
                    stack.appendChild(createNode("div", "chat-message-author-line", message.sender_fullname));
                }
            }

            var bubble = createNode(
                "article",
                "chat-message" +
                    (message.is_self ? " is-self" : "") +
                    (layout.continuesFromPrevious ? " is-continued-top" : "") +
                    (layout.continuesToNext ? " is-continued-bottom" : "") +
                    (!message.body_html && message.attachment ? " is-attachment-only" : "")
            );
            bubble.title = formatLastActivity(message.created_at) || message.created_at;

            if (message.body_html) {
                var body = createNode("div", "chat-message-body");
                body.innerHTML = message.body_html;
                bubble.appendChild(body);
            }

            if (message.attachment) {
                bubble.appendChild(buildAttachmentNode(message.attachment));
            }

            stack.appendChild(bubble);
            if (!layout.continuesToNext) {
                stack.appendChild(createNode(
                    "div",
                    "chat-message-stamp" + (message.is_self ? " is-self" : ""),
                    formatTimeOnly(message.created_at)
                ));
            }
            shell.appendChild(stack);
            return shell;
        }

        function renderThreadMessages() {
            refs.feed.innerHTML = "";

            if (!state.activeThread) {
                refs.feed.appendChild(createNode("div", "chat-empty-state", "Messages will appear here."));
                syncJumpLatestVisibility();
                return;
            }

            if (!state.threadMessages.length) {
                refs.feed.appendChild(createNode("div", "chat-empty-state", "No messages yet. Start the conversation."));
                syncJumpLatestVisibility();
                return;
            }

            var lastDateKey = "";
            state.threadMessages.forEach(function (message, index) {
                var previousMessage = index > 0 ? state.threadMessages[index - 1] : null;
                var nextMessage = index < state.threadMessages.length - 1 ? state.threadMessages[index + 1] : null;
                var continuesFromPrevious = canGroupMessages(previousMessage, message);
                var continuesToNext = canGroupMessages(message, nextMessage);
                var currentDateKey = getDateKey(message.created_at);
                if (currentDateKey && currentDateKey !== lastDateKey) {
                    var divider = createNode("div", "chat-date-divider");
                    divider.appendChild(createNode("span", "", formatDateDivider(message.created_at)));
                    refs.feed.appendChild(divider);
                    lastDateKey = currentDateKey;
                }

                refs.feed.appendChild(buildMessageNode(state.activeThread, message, {
                    continuesFromPrevious: continuesFromPrevious,
                    continuesToNext: continuesToNext,
                    showAvatar: !message.is_self && !continuesToNext
                }));
            });

            syncJumpLatestVisibility();
        }

        function renderThreadError(message) {
            state.activeThread = null;
            state.threadMessages = [];
            state.threadMeta = null;
            applyThreadHeader(null);
            refs.feed.innerHTML = "";
            refs.feed.appendChild(createNode("div", "chat-empty-state", message || "Unable to load this conversation."));
            refs.messageSummary.textContent = "Conversation unavailable";
            refs.messageStatus.textContent = "Try opening another conversation.";
            refs.loadOlder.hidden = true;
            refs.jumpLatest.hidden = true;
        }

        function reconcileThreadMeta() {
            if (!state.threadMeta) {
                return;
            }

            var loadedOldestId = getLoadedOldestId();
            var loadedNewestId = getLoadedNewestId();
            state.threadMeta.window_oldest_id = loadedOldestId;
            state.threadMeta.window_newest_id = loadedNewestId;
            state.threadMeta.has_more_before = !!(loadedOldestId && state.threadMeta.thread_oldest_id && loadedOldestId > state.threadMeta.thread_oldest_id);
            state.threadMeta.has_more_after = !!(loadedNewestId && state.threadMeta.thread_newest_id && loadedNewestId < state.threadMeta.thread_newest_id);
        }

        function applyThreadPayload(payload, mode) {
            state.activeThread = payload.thread;
            state.threadMeta = Object.assign({}, state.threadMeta || {}, payload.message_meta || {});

            if (mode === "prepend") {
                state.threadMessages = mergeMessages(payload.messages || [], state.threadMessages);
            } else if (mode === "append") {
                state.threadMessages = mergeMessages(state.threadMessages, payload.messages || []);
            } else {
                state.threadMessages = (payload.messages || []).slice();
            }

            reconcileThreadMeta();
            applyThreadHeader(state.activeThread);
            renderThreadMessages();
            updateThreadTools();
        }

        function clearComposer() {
            clearCurrentDraft();
            refs.composeInput.value = "";
            autoResizeComposer();
            refs.fileInput.value = "";
            refs.fileName.textContent = "No file selected";
            if (refs.filePreview) {
                refs.filePreview.hidden = true;
            }
            if (refs.fileChip) {
                refs.fileChip.textContent = "No file selected";
            }
            setComposeStatus("");
        }

        function setComposeStatus(message, tone) {
            if (!refs.composeStatus) {
                return;
            }
            refs.composeStatus.textContent = message || "";
            refs.composeStatus.classList.remove("is-error", "is-success");
            if (tone === "error" || tone === "success") {
                refs.composeStatus.classList.add("is-" + tone);
            }
        }

        function updateFilePreview() {
            var fileName = refs.fileInput.files && refs.fileInput.files.length ? refs.fileInput.files[0].name : "";
            refs.fileName.textContent = fileName || "No file selected";
            refs.fileName.hidden = !fileName;
            if (refs.fileChip) {
                refs.fileChip.textContent = fileName || "No file selected";
            }
            if (refs.filePreview) {
                refs.filePreview.hidden = !fileName;
            }
        }

        function setSending(isSending) {
            state.sending = !!isSending;
            refs.compose.classList.toggle("is-sending", state.sending);
            updateComposerAvailability();
        }

        function loadThread(type, target, options) {
            if (!type || !target) {
                return Promise.resolve();
            }

            var config = options || {};
            var sameThread = state.activeType === type && state.activeTarget === target;
            var mode = config.mode || "replace";
            var shouldStickToBottom = !!config.scrollToBottom;
            var previousMetrics = null;

            if (!sameThread) {
                saveCurrentDraft();
                refs.fileInput.value = "";
                updateFilePreview();
                setComposeStatus("");
            }

            if (sameThread && refs.feed) {
                previousMetrics = {
                    top: refs.feed.scrollTop,
                    height: refs.feed.scrollHeight
                };
            }

            state.activeType = type;
            state.activeTarget = target;
            setActiveTab(getTabForThread(type, config.tab));
            setSyncState("syncing");

            var url = new URL(root.dataset.threadUrl, window.location.origin);
            url.searchParams.set("type", type);
            url.searchParams.set("target", target);
            url.searchParams.set("limit", String(config.limit || (mode === "append" ? 80 : 40)));
            if (config.beforeId) {
                url.searchParams.set("before_id", String(config.beforeId));
            }
            if (config.afterId) {
                url.searchParams.set("after_id", String(config.afterId));
            }

            return fetchJson(url.toString()).then(function (payload) {
                syncOverview(payload.overview);

                if (mode === "append" && (!payload.messages || !payload.messages.length)) {
                    state.activeThread = payload.thread;
                    state.threadMeta = Object.assign({}, state.threadMeta || {}, payload.message_meta || {});
                    reconcileThreadMeta();
                    applyThreadHeader(state.activeThread);
                    updateThreadTools();
                    syncJumpLatestVisibility();
                    setSyncState("synced");
                    return payload;
                }

                applyThreadPayload(payload, mode);
                setPanelMode("chat");

                if (config.switchMobileView && isMobileLayout()) {
                    setMobileView("thread");
                }

                if (mode === "prepend" && previousMetrics) {
                    refs.feed.scrollTop = previousMetrics.top + (refs.feed.scrollHeight - previousMetrics.height);
                } else if (shouldStickToBottom) {
                    scrollFeedToBottom();
                } else if (previousMetrics) {
                    refs.feed.scrollTop = previousMetrics.top;
                }

                setSyncState("synced");
                return payload;
            }).catch(function (error) {
                setSettingsOpen(false);
                renderThreadError(error.message);
                setComposeStatus(error.message || "Unable to load this conversation.", "error");
                setSyncState("error");
                throw error;
            });
        }

        function loadOlderMessages() {
            if (state.loadingOlder || !state.activeThread || !state.threadMeta || !state.threadMeta.has_more_before) {
                return;
            }

            var oldestId = getLoadedOldestId();
            if (!oldestId) {
                return;
            }

            state.loadingOlder = true;
            updateThreadTools();
            loadThread(state.activeType, state.activeTarget, {
                mode: "prepend",
                beforeId: oldestId,
                scrollToBottom: false,
                tab: state.activeTab
            }).then(function () {
                return;
            }, function () {
                return;
            }).then(function () {
                state.loadingOlder = false;
                updateThreadTools();
            });
        }

        function refreshActiveThread() {
            if (!state.chatOpen || !state.activeType || !state.activeTarget) {
                return;
            }

            var newestId = getLoadedNewestId();
            loadThread(state.activeType, state.activeTarget, {
                mode: newestId ? "append" : "replace",
                afterId: newestId,
                scrollToBottom: isFeedNearBottom(),
                switchMobileView: false,
                tab: state.activeTab
            }).catch(function () {
                return;
            });
        }

        function refreshOverview() {
            if (document.hidden) {
                return;
            }

            if (state.chatOpen && state.activeType && state.activeTarget) {
                refreshActiveThread();
                return;
            }

            setSyncState("syncing");
            fetchJson(root.dataset.bootstrapUrl).then(function (payload) {
                syncOverview(payload.overview);
                if (state.chatOpen && !isMobileLayout() && !state.activeType) {
                    var firstItem = pickDefaultThread(payload.overview || {});
                    if (firstItem) {
                        setActiveTab(getTabForThread(firstItem.type, firstItem.tab));
                        loadThread(firstItem.type, firstItem.target, {
                            scrollToBottom: true,
                            tab: firstItem.tab,
                            switchMobileView: false,
                            mode: "replace"
                        }).catch(function () {
                            return;
                        });
                        return;
                    }
                }
                setSyncState("synced");
            }).catch(function () {
                setSyncState("error");
                return;
            });
        }

        refs.tabButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                if (button.dataset.chatTab === "channels" || button.dataset.chatTab === "roles") {
                    setPanelMode("channels");
                } else if (button.dataset.chatTab === "directs" || button.dataset.chatTab === "users") {
                    setPanelMode("messages");
                }
                setActiveTab(button.dataset.chatTab);
                if (isMobileLayout()) {
                    setMobileView("browse");
                    scrollTabListToTop(button.dataset.chatTab);
                }
                if (typeof button.blur === "function") {
                    button.blur();
                }
            });
        });

        refs.modeButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                var mode = button.dataset.chatMode === "channels"
                    ? "channels"
                    : (button.dataset.chatMode === "messages" ? "messages" : "chat");
                setPanelMode(mode);
                ensureTabForCurrentMode();
                if (mode !== "chat" && isMobileLayout()) {
                    setMobileView("browse");
                }
                if (mode === "chat" && !state.activeType && state.overview) {
                    var firstItem = pickDefaultThread(state.overview);
                    if (firstItem) {
                        setActiveTab(getTabForThread(firstItem.type, firstItem.tab));
                        loadThread(firstItem.type, firstItem.target, {
                            scrollToBottom: true,
                            tab: firstItem.tab,
                            switchMobileView: false,
                            mode: "replace"
                        }).catch(function () {
                            return;
                        });
                    }
                }
            });
        });

        refs.filterButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                state.filterMode = button.dataset.chatFilter || "all";
                refs.filterButtons.forEach(function (item) {
                    item.classList.toggle("is-active", item === button);
                });
                syncOverview(state.overview || {});
            });
        });

        if (refs.chatSearch) {
            refs.chatSearch.addEventListener("input", function () {
                state.searchTerm = normalizeSearch(refs.chatSearch.value);
                syncOverview(state.overview || {});
            });
        }

        if (refs.onlineSearch) {
            refs.onlineSearch.addEventListener("input", function () {
                state.onlineSearchTerm = normalizeSearch(refs.onlineSearch.value);
                renderOnlineUsers(state.overview || { users: [] });
            });
        }

        Array.prototype.slice.call(document.querySelectorAll("[data-profile-chat-search-input]")).forEach(function (input) {
            input.addEventListener("input", function () {
                renderProfileSearchPanels();
            });
        });

        refs.onlineTrigger.addEventListener("click", function (event) {
            event.stopPropagation();
            setOnlineOpen(!state.onlineOpen);
        });

        if (refs.onlineClose) {
            refs.onlineClose.addEventListener("click", function () {
                setOnlineOpen(false);
            });
        }

        refs.chatTrigger.addEventListener("click", function (event) {
            event.stopPropagation();
            setChatOpen(!state.chatOpen);
        });

        refs.close.addEventListener("click", function () {
            setChatOpen(false);
        });

        if (refs.refresh) {
            refs.refresh.addEventListener("click", function () {
                if (state.chatOpen && state.activeType && state.activeTarget) {
                    loadThread(state.activeType, state.activeTarget, {
                        scrollToBottom: false,
                        tab: state.activeTab,
                        switchMobileView: false,
                        mode: "replace"
                    }).catch(function () {
                        return;
                    });
                    return;
                }
                refreshOverview();
            });
        }

        if (refs.mobileBrowse) {
            refs.mobileBrowse.addEventListener("click", function () {
                if (state.activeType === "channel" || state.activeType === "role") {
                    setPanelMode("channels");
                } else {
                    setPanelMode("messages");
                }
                ensureTabForCurrentMode();
                setMobileView("browse");
                if (isMobileLayout() && state.activeTab === "users") {
                    scrollTabListToTop("users");
                }
            });
        }

        if (refs.mobileBack) {
            refs.mobileBack.addEventListener("click", function () {
                if (state.activeType === "channel" || state.activeType === "role") {
                    setPanelMode("channels");
                } else {
                    setPanelMode("messages");
                }
                ensureTabForCurrentMode();
                setMobileView("browse");
                if (isMobileLayout() && state.activeTab === "users") {
                    scrollTabListToTop("users");
                }
            });
        }

        if (refs.scrim) {
            refs.scrim.addEventListener("click", function () {
                closePanels();
            });
        }

        document.addEventListener("click", function (event) {
            if (!root.contains(event.target)) {
                closePanels();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closePanels();
            }
        });

        refs.editToggle.addEventListener("click", function () {
            setSettingsOpen(!state.settingsOpen);
        });

        refs.editCancel.addEventListener("click", function () {
            setSettingsOpen(false);
        });

        refs.channelForm.addEventListener("submit", function (event) {
            event.preventDefault();
            var formData = new FormData(refs.channelForm);
            setSyncState("syncing");
            fetchJson(root.dataset.channelUpdateUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                setSettingsOpen(false);
                syncOverview(payload.overview);
                if (state.activeType && state.activeTarget) {
                    loadThread(state.activeType, state.activeTarget, {
                        scrollToBottom: false,
                        tab: state.activeTab,
                        switchMobileView: false,
                        mode: "replace"
                    }).catch(function () {
                        return;
                    });
                } else {
                    setSyncState("synced");
                }
            }).catch(function () {
                setSyncState("error");
                return;
            });
        });

        refs.fileTrigger.addEventListener("click", function () {
            if (refs.fileInput.disabled) {
                return;
            }
            if (refs.fileTrigger.tagName === "BUTTON") {
                refs.fileInput.click();
            }
        });

        refs.fileInput.addEventListener("change", function () {
            var file = refs.fileInput.files && refs.fileInput.files.length ? refs.fileInput.files[0] : null;
            if (file && file.size > maxAttachmentSizeBytes) {
                refs.fileInput.value = "";
                updateFilePreview();
                setComposeStatus("Attachments must be 15 MB or smaller.", "error");
                return;
            }
            updateFilePreview();
            setComposeStatus(file ? "Attachment ready to send." : "");
        });

        if (refs.fileClear) {
            refs.fileClear.addEventListener("click", function () {
                refs.fileInput.value = "";
                updateFilePreview();
                if (!String(refs.composeInput.value || "").trim()) {
                    setComposeStatus("");
                }
            });
        }

        refs.composeInput.addEventListener("input", function () {
            saveCurrentDraft();
            autoResizeComposer();
            if (refs.composeStatus.classList.contains("is-error")) {
                setComposeStatus("");
            }
        });

        refs.composeInput.addEventListener("keydown", function (event) {
            if (isMobileLayout()) {
                return;
            }
            if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
                event.preventDefault();
                if (typeof refs.compose.requestSubmit === "function") {
                    refs.compose.requestSubmit();
                } else {
                    refs.compose.dispatchEvent(new Event("submit", {
                        bubbles: true,
                        cancelable: true
                    }));
                }
            }
        });

        refs.compose.addEventListener("submit", function (event) {
            event.preventDefault();
            if (!refs.composeType.value || !refs.composeTarget.value) {
                setComposeStatus("Select a conversation first.", "error");
                return;
            }

            if (state.sending) {
                return;
            }

            var hasMessage = !!String(refs.composeInput.value || "").trim();
            var hasFile = !!(refs.fileInput.files && refs.fileInput.files.length);
            if (!hasMessage && !hasFile) {
                setComposeStatus("Enter a message or attach a file.", "error");
                return;
            }

            var formData = new FormData(refs.compose);
            setSending(true);
            setComposeStatus("Sending...", "success");
            setSyncState("syncing");
            fetchJson(root.dataset.sendUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                clearComposer();
                syncOverview(payload.overview);
                applyThreadPayload(payload, "append");
                if (isMobileLayout()) {
                    setMobileView("thread");
                } else {
                    refs.composeInput.focus();
                }
                scrollFeedToBottom();
                setComposeStatus("Message sent.", "success");
                setSyncState("synced");
            }).catch(function (error) {
                setComposeStatus((error && error.message) || "Unable to send message or attachment.", "error");
                setSyncState("error");
            }).then(function () {
                setSending(false);
            }, function () {
                setSending(false);
            });
        });

        refs.feed.addEventListener("scroll", function () {
            syncJumpLatestVisibility();
        });

        refs.loadOlder.addEventListener("click", function () {
            loadOlderMessages();
        });

        refs.jumpLatest.addEventListener("click", function () {
            scrollFeedToBottom();
            syncJumpLatestVisibility();
        });

        function handleLayoutChange() {
            syncMobileControls();
            autoResizeComposer();
            if (!isMobileLayout() && state.chatOpen && !state.activeType && state.overview) {
                var firstItem = pickDefaultThread(state.overview);
                if (firstItem) {
                    setActiveTab(getTabForThread(firstItem.type, firstItem.tab));
                    loadThread(firstItem.type, firstItem.target, {
                        scrollToBottom: true,
                        tab: firstItem.tab,
                        switchMobileView: false,
                        mode: "replace"
                    }).catch(function () {
                        return;
                    });
                }
            }
            if (state.activeThread) {
                applyThreadHeader(state.activeThread);
            }
        }

        document.addEventListener("visibilitychange", function () {
            if (!document.hidden) {
                refreshOverview();
            }
        });

        document.addEventListener("click", function (event) {
            var openTrigger = event.target.closest("[data-chat-open-user]");
            if (openTrigger) {
                event.preventDefault();
                openDirectConversation(openTrigger.getAttribute("data-chat-open-user"), "directs").catch(function (error) {
                    setComposeStatus(error.message, "error");
                });
                return;
            }

            var favoriteTrigger = event.target.closest("[data-chat-favorite-toggle]");
            if (favoriteTrigger) {
                event.preventDefault();
                var targetUsername = favoriteTrigger.getAttribute("data-chat-favorite-toggle");
                var shouldFavorite = favoriteTrigger.getAttribute("data-chat-favorite-active") !== "true";
                toggleFavorite(targetUsername, shouldFavorite, favoriteTrigger).catch(function () {
                    return;
                });
            }
        });

        fetchJson(root.dataset.bootstrapUrl).then(function (payload) {
            syncOverview(payload.overview);
            applyThreadHeader(null);
            syncMobileControls();
            setPanelMode("messages");
            ensureTabForCurrentMode();
            autoResizeComposer();
            setSyncState("synced");
        }).catch(function () {
            setPanelMode("messages");
            ensureTabForCurrentMode();
            setSyncState("error");
            return;
        });

        if (mobileQuery.addEventListener) {
            mobileQuery.addEventListener("change", handleLayoutChange);
        } else if (mobileQuery.addListener) {
            mobileQuery.addListener(handleLayoutChange);
        }

        syncMobileControls();
        setPanelMode("messages");
        ensureTabForCurrentMode();
        autoResizeComposer();
        renderSyncStatus();
        state.pollHandle = window.setInterval(refreshOverview, Number(root.dataset.pollMs || 15000));
    }

    function init() {
        Array.prototype.slice.call(document.querySelectorAll("[data-chat-widget]")).forEach(initChatWidget);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
