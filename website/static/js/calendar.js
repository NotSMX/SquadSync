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
    var myName = window.squadScheduleMyName || '';
    var canSelect = !!token;
    var events = [];
    var myColor = colors[0];

    var colorMap = {};
    var colorIndex = 0;
    Object.keys(grouped).forEach(function(name) {
        colorMap[name] = colors[colorIndex % colors.length];
        if (name === myName) myColor = colorMap[name];
        colorIndex++;
    });

    function getColor(name) {
        if (!colorMap[name]) {
            colorMap[name] = colors[colorIndex % colors.length];
            colorIndex++;
        }
        return colorMap[name];
    }

    Object.keys(grouped).forEach(function(name) {
        var color = getColor(name);
        (grouped[name] || []).forEach(function(block) {
            if (block.start && block.end) {
                events.push({
                    title: name, start: block.start, end: block.end,
                    display: 'auto',
                    editable: name === myName,
                    interactive: name === myName,
                    classNames: name === myName ? ['fc-event-mine'] : [],
                    backgroundColor: (name === myName ? color + "99" : color + "20"),
                    borderColor: "transparent"
                });
            }
        });
    });

    document.documentElement.style.setProperty('--my-color', myColor);
    var s = document.createElement('style');
    s.textContent = '.fc .fc-event-mirror { background-color: ' + myColor + '99 !important; border-color: transparent !important; }';
    document.head.appendChild(s);

    var clearBtn = document.getElementById('clear-availability');
    if (clearBtn) {
        clearBtn.addEventListener('click', function() {
            if (!confirm("Clear all your availability?")) return;
            calendar.getEvents()
                .filter(function(e) { return e.title === myName; })
                .forEach(function(e) {
                    var fd = new FormData();
                    fd.append('token', token); fd.append('start', e.startStr); fd.append('end', e.endStr);
                    fetch('/session/' + sessionHash + '/remove_availability', {
                        method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                    });
                    e.remove();
                });
        });
    }

    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
        height: 500,
        slotMinTime: '06:00:00',
        slotMaxTime: '24:00:00',
        headerToolbar: { left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay' },
        events: events,
        nowIndicator: true,
        selectable: canSelect, editable: canSelect, selectMirror: false,
        selectOverlap: () => true,

        select: function(info) {
            if (!canSelect || !sessionHash || !token) return;
            var fd = new FormData();
            fd.append('token', token); fd.append('start', info.startStr); fd.append('end', info.endStr);
            fetch('/session/' + sessionHash + '/add_availability', {
                method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(function(data) {
                if (data && data.ok !== false) {
                    var newStart = info.start.getTime();
                    var newEnd = info.end.getTime();

                    calendar.getEvents()
                        .filter(function(e) {
                            return e.title === myName
                                && e.start.getTime() >= newStart
                                && e.end.getTime() <= newEnd;
                        })
                        .forEach(function(e) {
                            var fd = new FormData();
                            fd.append('token', token); fd.append('start', e.startStr); fd.append('end', e.endStr);
                            fetch('/session/' + sessionHash + '/remove_availability', {
                                method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                            });
                            e.remove();
                        });

                    calendar.addEvent({
                        title: myName, start: info.start, end: info.end,
                        display: 'auto', editable: true, interactive: true,
                        classNames: ['fc-event-mine'],
                        backgroundColor: myColor + "99", borderColor: "transparent"
                    });
                }
            });
        },

        eventClick: function(info) {
            if (info.event.title !== myName || !confirm("Remove this availability?")) return;
            var fd = new FormData();
            fd.append('token', token); fd.append('start', info.event.startStr); fd.append('end', info.event.endStr);
            fetch('/session/' + sessionHash + '/remove_availability', {
                method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(function(data) {
                if (!data || data.ok === false) { alert("Failed to remove availability."); return; }
                info.event.remove();
            })
            .catch(function() { info.event.remove(); });
        }
    });

    calendar.render();

    // ── SSE-driven live updates (replaces setInterval polling) ───────────────
    //
    // session_sse.js calls window.rebuildCalendar(availability) when the
    // server pushes a state change. We also listen for the custom event
    // as a fallback in case script load order varies.

    function rebuildCalendar(fresh) {
        if (!fresh) return;

        // Remove all other-people's events and re-add from fresh data
        calendar.getEvents()
            .filter(function(e) { return e.title !== myName; })
            .forEach(function(e) { e.remove(); });

        // Add new participants to the squad list if they've just joined
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

            if (name === myName) return;

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

    // Expose for session_sse.js
    window.rebuildCalendar = rebuildCalendar;

    // Also handle the custom-event fallback
    document.addEventListener('synq:availability', function(e) {
        rebuildCalendar(e.detail);
    });
});