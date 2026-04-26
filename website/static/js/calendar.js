document.addEventListener('DOMContentLoaded', function() {
    var calendarEl = document.getElementById('group-calendar');
    if (!calendarEl) return;

    var grouped = {};
    try {
        grouped = typeof window.squadScheduleData === 'string'
            ? JSON.parse(window.squadScheduleData)
            : (window.squadScheduleData || {});
    } catch (e) { grouped = {}; }

    var colors = ["#3b82f6","#ef4444","#22c55e","#eab308","#a855f7","#f97316"];
    var token = window.squadScheduleToken || '';
    var sessionHash = window.squadScheduleHash || '';
    
    // squadScheduleMyName is the real name once joined; fall back to temp label for pre-join
    var myName = window.squadScheduleMyName || 'You (Unsaved)';
    
    // Initialize global temp blocks array
    window.tempBlocks = [];

    var events = [];

    var colorMap = {};
    var colorIndex = 0;
    Object.keys(grouped).forEach(function(name) {
        if (!colorMap[name]) {
            colorMap[name] = colors[colorIndex % colors.length];
            colorIndex++;
        }
        var color = colorMap[name];
        // In experiment mode, there are no pre-loaded "mine" blocks — user starts fresh
        var isMine = (name === myName);

        (grouped[name] || []).forEach(function(block) {
            if (block.start && block.end) {
                events.push({
                    title: name,
                    start: block.start,
                    end: block.end,
                    display: 'auto',
                    editable: isMine,
                    startEditable: isMine,
                    durationEditable: isMine,
                    interactive: isMine,
                    classNames: isMine ? ['fc-event-mine'] : [],
                    backgroundColor: isMine ? color + "99" : color + "20",
                    borderColor: "transparent",
                    extendedProps: { 
                        startStr: block.start, 
                        endStr: block.end 
                    }
                });
            }
        });
    });

    function getColor(name) {
        if (!colorMap[name]) {
            colorMap[name] = colors[colorIndex % colors.length];
            colorIndex++;
        }
        return colorMap[name];
    }

    // Derive myColor AFTER the colorMap is built from grouped data so it
    // matches whatever color the server assigned to this participant's name.
    // For a brand-new pre-join visitor their name isn't in grouped yet, so
    // getColor() will assign the next available slot consistently.
    var myColor = getColor(myName);

    document.documentElement.style.setProperty('--my-color', myColor);
    var s = document.createElement('style');
    s.textContent = '.fc .fc-event-mirror { background-color: ' + myColor + '99 !important; border-color: transparent !important; }';
    document.head.appendChild(s);

    function toLocalISOString(date) {
        var off = date.getTimezoneOffset();
        var absOff = Math.abs(off);
        var sign = off <= 0 ? '+' : '-';
        var pad = function(n) { return String(n).padStart(2, '0'); };
        return date.getFullYear() + '-' +
            pad(date.getMonth() + 1) + '-' +
            pad(date.getDate()) + 'T' +
            pad(date.getHours()) + ':' +
            pad(date.getMinutes()) + ':' +
            pad(date.getSeconds()) +
            sign + pad(Math.floor(absOff / 60)) + ':' + pad(absOff % 60);
    }

    var clearBtn = document.getElementById('clear-availability');
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            if (!confirm("Clear all your availability?")) return;
            calendar.getEvents()
                .filter(function(e) { return e.title === window.squadScheduleMyName; })
                .forEach(function(e) {
                    var fd = new FormData();
                    fd.append('token', token);
                    fd.append('start', e.startStr);
                    fd.append('end', e.endStr);
                    fetch('/session/' + sessionHash + '/remove_availability', {
                        method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                    });
                    e.remove();
                });
        });
    }

    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: window.innerWidth < 768 ? 'timeGridDay' : 'timeGridWeek',
        height: 500,
        slotMinTime: '00:00:00',
        slotMaxTime: '24:00:00',
        slotLabelFormat: {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        },
        headerToolbar: { left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay' },
        events: events,
        nowIndicator: true,
        selectable: true, // Always true for unauthenticated users
        editable: true,
        eventStartEditable: true,
        eventDurationEditable: true,
        selectMirror: false,
        selectOverlap: true,
        longPressDelay: 1000,
        scrollTime: '08:00:00',
        handleWindowResize: true,
        stickyHeaderDates: true,
        selectLongPressDelay: 1000, 
        timeZone: 'local', 

        select: function(info) {
            if (!sessionHash && !window.isExperiment) return;
            
            window.usedCalendar = true;

            if (window.isExperiment) {
                window.tempBlocks.push({ start: info.startStr, end: info.endStr });
                document.dispatchEvent(new CustomEvent('calendar:block_added'));

                calendar.addEvent({
                    title: myName,
                    start: info.startStr,
                    end: info.endStr,
                    display: 'auto',
                    editable: true,
                    startEditable: true,
                    durationEditable: true,
                    interactive: true,
                    classNames: ['fc-event-mine'],
                    backgroundColor: myColor + "99",
                    borderColor: "transparent",
                    extendedProps: { 
                        temp: true, 
                        startStr: info.startStr, 
                        endStr: info.endStr 
                    }
                });
                return;
            }
            var newStart = info.start.getTime();
            var newEnd = info.end.getTime();

            // UNAUTHENTICATED FLOW
            if (!token) {
                calendar.getEvents()
                    .filter(e => e.title === myName && e.start.getTime() >= newStart && e.end.getTime() <= newEnd)
                    .forEach(e => {
                        if (e.extendedProps) {
                            window.tempBlocks = window.tempBlocks.filter(b => b.start !== e.extendedProps.startStr || b.end !== e.extendedProps.endStr);
                        }
                        e.remove();
                    });

                window.tempBlocks.push({ start: info.startStr, end: info.endStr });

                calendar.addEvent({
                    title: myName, 
                    start: info.startStr, 
                    end: info.endStr,
                    display: 'auto',
                    editable: true,
                    startEditable: true,
                    durationEditable: true,
                    interactive: true,
                    classNames: ['fc-event-mine'],
                    backgroundColor: myColor + "99", 
                    borderColor: "transparent",
                    extendedProps: { startStr: info.startStr, endStr: info.endStr }
                });
                return;
            }

            // AUTHENTICATED FLOW
            var fd = new FormData();
            fd.append('token', token);
            fd.append('start', info.startStr);
            fd.append('end', info.endStr);
            fetch('/session/' + sessionHash + '/add_availability', {
                method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(function(data) {
                if (data && data.ok !== false) {
                    calendar.getEvents()
                        .filter(function(e) {
                            return e.title === myName
                                && e.start.getTime() >= newStart
                                && e.end.getTime() <= newEnd;
                        })
                        .forEach(function(e) {
                            var fd = new FormData();
                            fd.append('token', token);
                            fd.append('start', e.startStr);
                            fd.append('end', e.endStr);
                            fetch('/session/' + sessionHash + '/remove_availability', {
                                method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                            });
                            e.remove();
                        });

                    calendar.addEvent({
                        title: myName, start: info.startStr, end: info.endStr,
                        display: 'auto', editable: true, interactive: true,
                        classNames: ['fc-event-mine'],
                        backgroundColor: myColor + "99", borderColor: "transparent",
                        extendedProps: { startStr: info.startStr, endStr: info.endStr }
                    });
                }
            });
        },

        selectAllow: function(selectInfo) {
            const now = new Date();
            return selectInfo.start >= now;
        },

        eventAllow: function(dropInfo, draggedEvent) {
            const now = new Date();
            return dropInfo.start >= now;
        },

        validRange: function(nowDate) {
            return {
                start: nowDate
            };
        },

        eventClick: function(info) {
            window.usedCalendar = true;
            if (window.matchMedia('(pointer: coarse)').matches) return;

            // Check if it's "mine" in any of the three possible ways
            const isMine = info.event.title === myName || 
                        info.event.title === window.squadScheduleMyName ||
                        window.isExperiment;

            if (!isMine) return;

            if (!confirm("Remove this availability?")) return;
            handleEventRemoval(info.event);
        },

        eventDidMount: function(info) {
            if (!window.matchMedia('(pointer: coarse)').matches) return;
            if (!window.isExperiment &&
                info.event.title !== myName &&
                info.event.title !== window.squadScheduleMyName) return;

            let pressTimer = null;

            info.el.addEventListener('touchstart', function(e) {
                pressTimer = setTimeout(function() {
                    if (!confirm("Remove this availability?")) return;
                    handleEventRemoval(info.event);
                }, 1500);
            });

            info.el.addEventListener('touchend', function() {
                clearTimeout(pressTimer);
            });

            info.el.addEventListener('touchmove', function() {
                clearTimeout(pressTimer);
            });
        },
        
        eventDrop: function(info) {
            window.usedCalendar = true;
            if (window.isExperiment) {
                // Use extendedProps keys for matching — they're set at create-time
                // and avoid any UTC-vs-local-offset mismatch with .toISOString().
                var oldStart = info.oldEvent.extendedProps && info.oldEvent.extendedProps.startStr
                    ? info.oldEvent.extendedProps.startStr
                    : info.oldEvent.startStr;
                var oldEnd = info.oldEvent.extendedProps && info.oldEvent.extendedProps.endStr
                    ? info.oldEvent.extendedProps.endStr
                    : info.oldEvent.endStr;

                var newStart = info.event.startStr;
                var newEnd   = info.event.endStr;

                window.tempBlocks = window.tempBlocks.map(function(b) {
                    if (b.start === oldStart && b.end === oldEnd) {
                        return { start: newStart, end: newEnd };
                    }
                    return b;
                });

                // Keep extendedProps in sync for future edits/removals
                info.event.setExtendedProp('startStr', newStart);
                info.event.setExtendedProp('endStr', newEnd);

                document.dispatchEvent(new CustomEvent('synq:availability', {
                    detail: {
                        [myName]: window.tempBlocks
                    }
                }));

                return;
            }

            if (!window.isExperiment) {
                if (info.event.title !== myName && info.event.title !== window.squadScheduleMyName) {
                    info.revert();
                    return;
                }
            }

            var oldFd = new FormData();
            oldFd.append('token', token);
            oldFd.append('start', info.oldEvent.startStr);
            oldFd.append('end', info.oldEvent.endStr);
            fetch('/session/' + sessionHash + '/remove_availability', {
                method: 'POST', body: oldFd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(function(data) {
                if (!data || data.ok === false) { info.revert(); return; }

                var newFd = new FormData();
                newFd.append('token', token);
                newFd.append('start', info.event.startStr);
                newFd.append('end', info.event.endStr);
                return fetch('/session/' + sessionHash + '/add_availability', {
                    method: 'POST', body: newFd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                .then(r => r.json())
                .then(function(addData) {
                    if (!addData || addData.ok === false) { info.revert(); return; }
                    info.event.setExtendedProp('startStr', info.event.startStr);
                    info.event.setExtendedProp('endStr', info.event.endStr);
                });
            })
            .catch(function() { info.revert(); });
        },
    });

    calendar.render();

    function handleEventRemoval(event) {
        if (window.isExperiment) {
            // Keep tempBlocks in sync so deleted events aren't submitted on join
            var ep = event.extendedProps || {};
            var startKey = ep.startStr || event.startStr;
            var endKey   = ep.endStr   || event.endStr;
            window.tempBlocks = window.tempBlocks.filter(function(b) {
                return !(b.start === startKey && b.end === endKey);
            });
            event.remove();
            return;
        }
        // Handle unauthenticated removal
        if (!token) {
            if (event.extendedProps) {
                window.tempBlocks = window.tempBlocks.filter(b => b.start !== event.extendedProps.startStr || b.end !== event.extendedProps.endStr);
            }
            event.remove();
            return;
        }

        // Handle authenticated removal
        var fd = new FormData();
        fd.append('token', token);
        fd.append('start', event.startStr);
        fd.append('end', event.endStr);
        fetch('/session/' + sessionHash + '/remove_availability', {
            method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(r => r.json())
        .then(function(data) {
            if (!data || data.ok === false) { alert("Failed to remove availability."); return; }
            event.remove();
        })
        .catch(function() { event.remove(); });
    }

    function rebuildCalendar(fresh) {
        if (!fresh) return;

        calendar.getEvents()
            .filter(function(e) { return e.title !== myName && e.title !== window.squadScheduleMyName; })
            .forEach(function(e) { e.remove(); });

        var squadList = document.getElementById('squad-list');
        Object.keys(fresh).forEach(function(name) {
            var color = getColor(name);

            if (squadList && !squadList.querySelector('[data-name="' + CSS.escape(name) + '"]')) {
                var card = document.createElement('div');
                card.className = 'squad-card';
                card.setAttribute('data-name', name);
                var pill = document.createElement('div');
                pill.className = 'squad-pill';
                pill.style.background = color;
                pill.textContent = name;
                card.appendChild(pill);
                squadList.appendChild(card);
            }

            if (name === window.squadScheduleMyName) return;

            (fresh[name] || []).forEach(function(block) {
                if (block.start && block.end) {
                    calendar.addEvent({
                        title: name, start: block.start, end: block.end,
                        display: 'auto', editable: false, interactive: false,
                        backgroundColor: color + "20",
                        borderColor: "transparent"
                    });
                }
            });
        });
    }

});