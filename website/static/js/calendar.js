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
    
    // Default name for unauthenticated users
    var myName = window.squadScheduleMyName || 'You (Unsaved)';
    
    // Initialize global temp blocks array
    window.tempBlocks = [];

    var events = [];
    var myColor = colors[0];

    var colorMap = {};
    var colorIndex = 0;
    Object.keys(grouped).forEach(function(name) {
        colorMap[name] = colors[colorIndex % colors.length];
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
                    fd.append('start', toLocalISOString(e.start));
                    fd.append('end', toLocalISOString(e.end));
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
        slotMinTime: '06:00:00',
        slotMaxTime: '24:00:00',
        headerToolbar: { left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay' },
        events: events,
        nowIndicator: true,
        selectable: true, // Always true for unauthenticated users
        editable: true,   // Always true for unauthenticated users
        selectMirror: false,
        selectOverlap: true,
        longPressDelay: 300,
        selectLongPressDelay: 300, 
        timeZone: 'UTC', 

        select: function(info) {
            if (!sessionHash) return;
            
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
                    title: myName, start: info.start, end: info.end,
                    display: 'auto', editable: true, interactive: true,
                    classNames: ['fc-event-mine'],
                    backgroundColor: myColor + "99", borderColor: "transparent",
                    extendedProps: { startStr: info.startStr, endStr: info.endStr }
                });
                return;
            }

            // AUTHENTICATED FLOW
            var fd = new FormData();
            fd.append('token', token);
            fd.append('start', toLocalISOString(info.start));
            fd.append('end', toLocalISOString(info.end));
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
                            fd.append('start', toLocalISOString(e.start));
                            fd.append('end', toLocalISOString(e.end));
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
            // Desktop only — touch uses long-press
            if (window.matchMedia('(pointer: coarse)').matches) return;
            if (info.event.title !== myName && info.event.title !== window.squadScheduleMyName) return;
            if (!confirm("Remove this availability?")) return;
            handleEventRemoval(info.event);
        },

        eventDidMount: function(info) {
            if (!window.matchMedia('(pointer: coarse)').matches) return;
            if (info.event.title !== myName && info.event.title !== window.squadScheduleMyName) return;

            let pressTimer = null;

            info.el.addEventListener('touchstart', function(e) {
                pressTimer = setTimeout(function() {
                    if (!confirm("Remove this availability?")) return;
                    handleEventRemoval(info.event);
                }, 600);
            }, { passive: true });

            info.el.addEventListener('touchend', function() {
                clearTimeout(pressTimer);
            });

            info.el.addEventListener('touchmove', function() {
                clearTimeout(pressTimer);
            });
        },
        
        eventDrop: function(info) {
            if (info.event.title !== myName && info.event.title !== window.squadScheduleMyName) { info.revert(); return; }
            if (!token) { info.revert(); return; } // Prevent dragging temp blocks for now

            var oldFd = new FormData();
            oldFd.append('token', token);
            oldFd.append('start', toLocalISOString(info.oldEvent.start));
            oldFd.append('end', toLocalISOString(info.oldEvent.end)); 
            fetch('/session/' + sessionHash + '/remove_availability', {
                method: 'POST', body: oldFd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(function(data) {
                if (!data || data.ok === false) { info.revert(); return; }

                var newFd = new FormData();
                newFd.append('token', token);
                newFd.append('start', toLocalISOString(info.event.start));
                newFd.append('end', toLocalISOString(info.event.end));
                return fetch('/session/' + sessionHash + '/add_availability', {
                    method: 'POST', body: newFd, headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
            })
            .catch(function() { info.revert(); });
        },
    });

    calendar.render();

    function handleEventRemoval(event) {
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
        fd.append('start', toLocalISOString(event.start));
        fd.append('end', toLocalISOString(event.end));
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

    window.rebuildCalendar = rebuildCalendar;

    document.addEventListener('synq:availability', function(e) {
        rebuildCalendar(e.detail);
    });
});