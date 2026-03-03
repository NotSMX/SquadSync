const slides = document.querySelectorAll(".bg-slide");
let current = 0;

function nextSlide() {
    slides[current].classList.remove("active");
    current = (current + 1) % slides.length;
    slides[current].classList.add("active");
}

setInterval(nextSlide, 6000);