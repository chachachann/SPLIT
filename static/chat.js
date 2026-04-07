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

    function parseTimestamp(value) {
        var match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (!match) {
            return null;
        }
        return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
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
        var state = {
            activeType: "",
            activeTarget: "",
            activeThread: null,
            overview: null,
            pollHandle: 0,
            chatOpen: false,
            onlineOpen: false,
            activeTab: "channels",
            settingsOpen: false,
            mobileView: "browse",
            threadMessages: [],
            threadMeta: null,
            loadingOlder: false
        };

        var refs = {
            scrim: root.querySelector("[data-chat-scrim]"),
            onlineTrigger: root.querySelector("[data-online-trigger]"),
            onlineBadge: root.querySelector("[data-online-badge]"),
            onlinePanel: root.querySelector("[data-online-panel]"),
            onlineSummary: root.querySelector("[data-online-summary]"),
            onlineList: root.querySelector("[data-online-list]"),
            onlineClose: root.querySelector("[data-online-close]"),
            chatTrigger: root.querySelector("[data-chat-trigger]"),
            chatBadge: root.querySelector("[data-chat-badge]"),
            chatPanel: root.querySelector("[data-chat-panel]"),
            chatSummary: root.querySelector("[data-chat-summary]"),
            mobileBrowse: root.querySelector("[data-chat-mobile-browse]"),
            close: root.querySelector("[data-chat-close]"),
            tabButtons: Array.prototype.slice.call(root.querySelectorAll("[data-chat-tab]")),
            tabPanes: Array.prototype.slice.call(root.querySelectorAll("[data-chat-pane]")),
            channelList: root.querySelector('[data-chat-list="channels"]'),
            roleList: root.querySelector('[data-chat-list="roles"]'),
            directList: root.querySelector('[data-chat-list="directs"]'),
            userList: root.querySelector('[data-chat-list="users"]'),
            threadAvatar: root.querySelector("[data-chat-thread-avatar]"),
            threadAvatarText: root.querySelector("[data-chat-thread-avatar-text]"),
            threadAvatarStatus: root.querySelector("[data-chat-thread-avatar-status]"),
            kicker: root.querySelector("[data-chat-thread-kicker]"),
            title: root.querySelector("[data-chat-thread-title]"),
            subtitle: root.querySelector("[data-chat-thread-subtitle]"),
            editToggle: root.querySelector("[data-chat-edit-toggle]"),
            mobileBack: root.querySelector("[data-chat-mobile-back]"),
            channelForm: root.querySelector("[data-chat-channel-form]"),
            channelRoomKey: root.querySelector("[data-chat-channel-room-key]"),
            channelTitleInput: root.querySelector("[data-chat-channel-title-input]"),
            channelDescriptionInput: root.querySelector("[data-chat-channel-description-input]"),
            editCancel: root.querySelector("[data-chat-edit-cancel]"),
            messageSummary: root.querySelector("[data-chat-message-summary]"),
            messageStatus: root.querySelector("[data-chat-message-status]"),
            loadOlder: root.querySelector("[data-chat-load-older]"),
            jumpLatest: root.querySelector("[data-chat-jump-latest]"),
            feed: root.querySelector("[data-chat-messages]"),
            compose: root.querySelector("[data-chat-compose]"),
            composeType: root.querySelector("[data-chat-compose-type]"),
            composeTarget: root.querySelector("[data-chat-compose-target]"),
            composeInput: root.querySelector("[data-chat-compose-input]"),
            fileInput: root.querySelector("[data-chat-file-input]"),
            fileTrigger: root.querySelector("[data-chat-file-trigger]"),
            fileName: root.querySelector("[data-chat-file-name]"),
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

        function setActiveTab(tabName) {
            state.activeTab = tabName;
            refs.tabButtons.forEach(function (button) {
                button.classList.toggle("is-active", button.dataset.chatTab === tabName);
            });
            refs.tabPanes.forEach(function (pane) {
                pane.classList.toggle("is-active", pane.dataset.chatPane === tabName);
            });
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
            refs.chatSummary.textContent = unread === 1 ? "1 unread" : String(unread) + " unread";
        }

        function updateOnlineBadge(total) {
            var online = Number(total || 0);
            refs.onlineBadge.hidden = online <= 0;
            refs.onlineBadge.textContent = online > 99 ? "99+" : String(online);
            refs.onlineSummary.textContent = online === 1 ? "1 online" : String(online) + " online";
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

        function buildListItem(config) {
            var button = createNode("button", "chat-list-item");
            button.type = "button";
            button.dataset.chatType = config.type;
            button.dataset.chatTarget = config.target;
            if (isItemActive(config.type, config.target)) {
                button.classList.add("is-active");
            }

            var main = createNode("div", "chat-list-item-main");
            var avatar = createNode("span", "chat-list-item-avatar" + (config.avatarTone ? " chat-list-item-avatar-" + config.avatarTone : ""), config.avatarText);
            if (config.status) {
                avatar.appendChild(createNode("span", "chat-list-item-avatar-status" + (config.status === "online" ? " is-online" : "")));
            }
            main.appendChild(avatar);

            var copy = createNode("div", "chat-list-item-copy");
            var titleRow = createNode("div", "chat-list-item-row");
            titleRow.appendChild(createNode("div", "chat-list-item-title", config.title));

            var tail = createNode("div", "chat-list-item-tail");
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
                copy.appendChild(createNode("div", "chat-list-item-note", config.note));
            }

            main.appendChild(copy);
            button.appendChild(main);
            button.addEventListener("click", function () {
                setChatOpen(true);
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
            return button;
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
            var onlineUsers = (overview.users || []).filter(function (item) {
                return item.presence === "online";
            });
            updateOnlineBadge(onlineUsers.length);
            refs.onlineList.innerHTML = "";
            if (!onlineUsers.length) {
                refs.onlineList.appendChild(createNode("div", "chat-empty-state chat-empty-state-compact", "No online users right now."));
                return;
            }

            onlineUsers.forEach(function (user) {
                var button = createNode("button", "online-user-item");
                button.type = "button";

                var avatar = createNode("span", "chat-list-item-avatar chat-list-item-avatar-person", getInitials(user.fullname, "U"));
                avatar.appendChild(createNode("span", "chat-list-item-avatar-status is-online"));

                var copy = createNode("div", "online-user-copy");
                copy.appendChild(createNode("strong", "", user.fullname));
                copy.appendChild(createNode("span", "", joinBits([user.designation, buildHandle(user.username)]) || "Currently online"));

                button.appendChild(avatar);
                button.appendChild(copy);
                button.addEventListener("click", function () {
                    setOnlineOpen(false);
                    setChatOpen(true);
                    setActiveTab("directs");
                    loadThread("direct", user.username, {
                        scrollToBottom: true,
                        tab: "directs",
                        switchMobileView: true,
                        mode: "replace"
                    }).catch(function () {
                        return;
                    });
                });
                refs.onlineList.appendChild(button);
            });
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
            updateTabCounts(state.overview);
            renderOnlineUsers(state.overview);

            renderList(refs.channelList, state.overview.channels, function (item) {
                return buildListItem({
                    type: "channel",
                    tab: "channels",
                    target: item.room_key,
                    title: item.title,
                    subtitle: item.description || "Public room",
                    note: item.last_message_preview || "No messages yet",
                    unreadCount: item.unread_count || 0,
                    avatarText: getChannelBadge(item.room_key),
                    avatarTone: "channel"
                });
            }, "No channels available.");

            renderList(refs.roleList, state.overview.role_groups, function (item) {
                return buildListItem({
                    type: "role",
                    tab: "roles",
                    target: item.room_key,
                    title: item.title,
                    subtitle: item.description || (item.role_name ? item.role_name + " group" : "Role-based room"),
                    note: item.last_message_preview || "No messages yet",
                    unreadCount: item.unread_count || 0,
                    avatarText: getInitials(item.role_name || item.title, "RG"),
                    avatarTone: "role"
                });
            }, "No role groups available.");

            renderList(refs.directList, state.overview.direct_threads, function (item) {
                return buildListItem({
                    type: "direct",
                    tab: "directs",
                    target: item.target_username,
                    title: item.title,
                    subtitle: joinBits([item.description, buildHandle(item.target_username)]),
                    note: item.last_message_preview || "No messages yet",
                    unreadCount: item.unread_count || 0,
                    meta: item.presence_label || "Offline",
                    metaTone: item.presence || "offline",
                    status: item.presence,
                    avatarText: getInitials(item.title, "DM"),
                    avatarTone: "direct"
                });
            }, "No direct conversations yet.");

            renderList(refs.userList, state.overview.users, function (item) {
                var presenceNote = item.presence === "online" ? "Currently online" : "Last active " + (item.last_seen_label || item.last_login_at || "Not available");
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
                    avatarText: getInitials(item.fullname, "U"),
                    avatarTone: "person"
                });
            }, "No other users found.");
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

        function applyThreadHeader(thread) {
            if (!thread) {
                refs.kicker.textContent = "Conversation";
                refs.title.textContent = "Select a conversation";
                refs.subtitle.textContent = "Open a channel, role room, or direct message.";
                refs.threadAvatar.className = "chat-thread-avatar";
                refs.threadAvatarText.textContent = "?";
                refs.threadAvatarStatus.hidden = true;
                refs.composeType.value = "";
                refs.composeTarget.value = "";
                setSettingsOpen(false);
                updateThreadTools();
                return;
            }

            refs.title.textContent = thread.title || "Conversation";

            var kicker = "Conversation";
            var subtitle = thread.description || "";
            var avatarText = "?";
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
                    thread.presence ? thread.presence.status_label : ""
                ]);
                avatarText = getInitials(thread.title, "DM");
                avatarTone = "direct";
                directStatus = thread.presence ? thread.presence.status : "";
                if (thread.presence && !thread.presence.is_online) {
                    subtitle = joinBits([
                        subtitle,
                        thread.presence.last_seen_at ? "Last active " + thread.presence.last_seen_at : "",
                        !thread.presence.last_seen_at && thread.presence.last_login_at ? "Last login " + thread.presence.last_login_at : ""
                    ]);
                }
            }

            refs.kicker.textContent = kicker;
            refs.subtitle.textContent = subtitle || "Conversation ready.";
            refs.threadAvatar.className = "chat-thread-avatar chat-thread-avatar-" + avatarTone;
            refs.threadAvatarText.textContent = avatarText;
            refs.threadAvatarStatus.hidden = !directStatus;
            refs.threadAvatarStatus.classList.toggle("is-online", directStatus === "online");
            refs.channelRoomKey.value = thread.editable ? thread.room_key : "";
            refs.channelTitleInput.value = thread.editable ? (thread.title || "") : "";
            refs.channelDescriptionInput.value = thread.editable ? (thread.description || "") : "";
            refs.composeType.value = thread.thread_type;
            refs.composeTarget.value = thread.thread_type === "direct" ? thread.target_username : thread.room_key;

            setSettingsOpen(false);
            syncMobileControls();
            updateThreadTools();
        }

        function buildMessageNode(thread, message) {
            var showAuthor = thread.thread_type !== "direct" && !message.is_self;
            var shell = createNode("div", "chat-message-shell" + (message.is_self ? " is-self" : ""));

            if (!message.is_self) {
                shell.appendChild(createNode("span", "chat-message-avatar", getInitials(message.sender_fullname, "U")));
            }

            var stack = createNode("div", "chat-message-stack");
            if (showAuthor) {
                stack.appendChild(createNode("div", "chat-message-author-line", message.sender_fullname));
            }

            var bubble = createNode("article", "chat-message" + (message.is_self ? " is-self" : ""));

            if (message.body_html) {
                var body = createNode("div", "chat-message-body");
                body.innerHTML = message.body_html;
                bubble.appendChild(body);
            }

            if (message.attachment) {
                var attachment = createNode("div", "chat-attachment");
                var attachmentLink = createNode("a", "chat-attachment-link", message.attachment.name);
                attachmentLink.href = message.attachment.url;
                attachmentLink.target = "_blank";
                attachmentLink.rel = "noopener noreferrer";
                attachment.appendChild(attachmentLink);

                if (message.attachment.kind === "image") {
                    var imageLink = createNode("a", "chat-attachment-preview");
                    imageLink.href = message.attachment.url;
                    imageLink.target = "_blank";
                    imageLink.rel = "noopener noreferrer";
                    var image = createNode("img");
                    image.src = message.attachment.url;
                    image.alt = message.attachment.name;
                    imageLink.appendChild(image);
                    attachment.appendChild(imageLink);
                }

                bubble.appendChild(attachment);
            }

            stack.appendChild(bubble);
            stack.appendChild(createNode("div", "chat-message-stamp" + (message.is_self ? " is-self" : ""), message.created_at));
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
            state.threadMessages.forEach(function (message) {
                var currentDateKey = getDateKey(message.created_at);
                if (currentDateKey && currentDateKey !== lastDateKey) {
                    var divider = createNode("div", "chat-date-divider");
                    divider.appendChild(createNode("span", "", formatDateDivider(message.created_at)));
                    refs.feed.appendChild(divider);
                    lastDateKey = currentDateKey;
                }

                refs.feed.appendChild(buildMessageNode(state.activeThread, message));
            });

            syncJumpLatestVisibility();
        }

        function renderThreadError(message) {
            state.threadMessages = [];
            state.threadMeta = null;
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
            refs.composeInput.value = "";
            refs.fileInput.value = "";
            refs.fileName.textContent = "No file selected";
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

        function loadThread(type, target, options) {
            if (!type || !target) {
                return Promise.resolve();
            }

            var config = options || {};
            var sameThread = state.activeType === type && state.activeTarget === target;
            var mode = config.mode || "replace";
            var shouldStickToBottom = !!config.scrollToBottom;
            var previousMetrics = null;

            if (sameThread && refs.feed) {
                previousMetrics = {
                    top: refs.feed.scrollTop,
                    height: refs.feed.scrollHeight
                };
            }

            state.activeType = type;
            state.activeTarget = target;
            setActiveTab(getTabForThread(type, config.tab));

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
                    return payload;
                }

                applyThreadPayload(payload, mode);

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

                return payload;
            }).catch(function (error) {
                setSettingsOpen(false);
                renderThreadError(error.message);
                setComposeStatus(error.message || "Unable to load this conversation.", "error");
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
            if (state.chatOpen && state.activeType && state.activeTarget) {
                refreshActiveThread();
                return;
            }

            fetchJson(root.dataset.bootstrapUrl).then(function (payload) {
                syncOverview(payload.overview);
            }).catch(function () {
                return;
            });
        }

        refs.tabButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                setActiveTab(button.dataset.chatTab);
                if (isMobileLayout()) {
                    setMobileView("browse");
                }
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

        if (refs.mobileBrowse) {
            refs.mobileBrowse.addEventListener("click", function () {
                setMobileView("browse");
            });
        }

        if (refs.mobileBack) {
            refs.mobileBack.addEventListener("click", function () {
                setMobileView("browse");
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
                }
            }).catch(function () {
                return;
            });
        });

        refs.fileTrigger.addEventListener("click", function () {
            if (refs.fileTrigger.tagName === "BUTTON") {
                refs.fileInput.click();
            }
        });

        refs.fileInput.addEventListener("change", function () {
            var fileName = refs.fileInput.files && refs.fileInput.files.length ? refs.fileInput.files[0].name : "";
            refs.fileName.textContent = fileName || "No file selected";
            setComposeStatus(fileName ? "Attachment ready to send." : "");
        });

        refs.compose.addEventListener("submit", function (event) {
            event.preventDefault();
            if (!refs.composeType.value || !refs.composeTarget.value) {
                setComposeStatus("Select a conversation first.", "error");
                return;
            }

            var formData = new FormData(refs.compose);
            setComposeStatus("Sending...", "success");
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
            }).catch(function (error) {
                setComposeStatus((error && error.message) || "Unable to send message or attachment.", "error");
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
        }

        fetchJson(root.dataset.bootstrapUrl).then(function (payload) {
            syncOverview(payload.overview);
            applyThreadHeader(null);
            syncMobileControls();
        }).catch(function () {
            return;
        });

        if (mobileQuery.addEventListener) {
            mobileQuery.addEventListener("change", handleLayoutChange);
        } else if (mobileQuery.addListener) {
            mobileQuery.addListener(handleLayoutChange);
        }

        syncMobileControls();
        state.pollHandle = window.setInterval(refreshOverview, Number(root.dataset.pollMs || 60000));
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
