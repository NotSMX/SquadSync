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
    
    // Default name for unauthenticated users so their blocks show up nicely
    var myName = window.squadScheduleMyName || 'You (Unsaved)'; 
    
    // Initialize the global array to hold temporary blocks for the join form
    window.tempBlocks = [];

    var events = [];
    var myColor = colors[0];

    var colorMap = {};
    var colorIndex = 0;
    Object.keys(grouped).forEach(function(name) {
        colorMap[name] = colors[colorIndex % colors.length];
        // Use actual logged-in name to find color, ignoring the "Unsaved" default
        if (name === window.squadScheduleMyName) myColor = colorMap[name]; 
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
                    editable: name === window.squadScheduleMyName,
                    interactive: name === window.squadScheduleMyName,
                    classNames: name === window.squadScheduleMyName ? ['fc-event-mine'] : [],
                    backgroundColor: (name === window.squadScheduleMyName ? color + "99" : color + "20"),
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
                .filter(function(e) { return e.title === myName || e.title === window.squadScheduleMyName; })
                .forEach(function(e) {
                    if (token) {
                        var fd = new FormData();
                        fd.append('token', token); fd.append('start', e.startStr); fd.append('end', e.endStr);
                        fetch('/session/' + sessionHash + '/remove_availability', {
                            method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                        });
                    } else {
                        window.tempBlocks = [];
                    }
                    e.remove();
                });
        });
    }

    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: window.innerWidth < 768 ? 'timeGridDay' : 'timeGridWeek',
        height: 500,
        slotMinTime: '06:00:00',
        slotMaxTime: '24:00:00',
        headerToolbar: { left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay' },
        events: events,
        nowIndicator: true,
        selectable: true, // Always allow selection, even if not logged in
        editable: true,   // Always allow editing
        selectMirror: false,
        selectOverlap: true,
        longPressDelay: 300,
        selectLongPressDelay: 300,  

        select: function(info) {
            if (!sessionHash) return;
            
            var newStart = info.start.getTime();
            var newEnd = info.end.getTime();

            // --- UNAUTHENTICATED FLOW (Temp Blocks) ---
            if (!token) {
                // Remove overlapping temp events from UI and array
                calendar.getEvents()
                    .filter(e => e.title === myName && e.start.getTime() >= newStart && e.end.getTime() <= newEnd)
                    .forEach(e => {
                        // Filter out of temp array using extendedProps
                        if (e.extendedProps) {
                            window.tempBlocks = window.tempBlocks.filter(b => b.start !== e.extendedProps.startStr || b.end !== e.extendedProps.endStr);
                        }
                        e.remove();
                    });

                // Save new block to global array
                window.tempBlocks.push({ start: info.startStr, end: info.endStr });

                // Render locally
                calendar.addEvent({
                    title: myName, start: info.start, end: info.end,
                    display: 'auto', editable: true, interactive: true,
                    classNames: ['fc-event-mine'],
                    backgroundColor: myColor + "99", borderColor: "transparent",
                    extendedProps: { startStr: info.startStr, endStr: info.endStr }
                });
                return;
            }

            // --- AUTHENTICATED FLOW (Original backend save) ---
            var fd = new FormData();
            fd.append('token', token); fd.append('start', info.startStr); fd.append('end', info.endStr);
            fetch('/session/' + sessionHash + '/add_availability', {
                method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(function(data) {
                if (data && data.ok !== false) {
                    calendar.getEvents()
                        .filter(e => e.title === myName && e.start.getTime() >= newStart && e.end.getTime() <= newEnd)
                        .forEach(e => {
                            var fdRem = new FormData();
                            fdRem.append('token', token); fdRem.append('start', e.startStr); fdRem.append('end', e.endStr);
                            fetch('/session/' + sessionHash + '/remove_availability', {
                                method: 'POST', body: fdRem, headers: { 'X-Requested-With': 'XMLHttpRequest' }
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
            // Only allow removing your own events
            if (info.event.title !== myName && info.event.title !== window.squadScheduleMyName) return;
            if (!confirm("Remove this availability?")) return;
            
            // --- UNAUTHENTICATED FLOW ---
            if (!token) {
                if (info.event.extendedProps) {
                    window.tempBlocks = window.tempBlocks.filter(b => b.start !== info.event.extendedProps.startStr || b.end !== info.event.extendedProps.endStr);
                }
                info.event.remove();
                return;
            }

            // --- AUTHENTICATED FLOW ---
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

    // ── SSE-driven live updates ───────────────
    function rebuildCalendar(fresh) {
        if (!fresh) return;

        // Remove others' events
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

    window.rebuildCalendar = rebuildCalendar;

    document.addEventListener('synq:availability', function(e) {
        rebuildCalendar(e.detail);
    });
});